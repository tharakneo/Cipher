import { Ionicons } from '@expo/vector-icons';
import { Audio } from 'expo-av';
import * as ImagePicker from 'expo-image-picker';
import { LinearGradient } from 'expo-linear-gradient';
import * as Notifications from 'expo-notifications';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Dimensions,
  Image,
  Linking,
  Modal,
  NativeModules,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';

const { AudioSessionModule } = NativeModules;

const { height: SCREEN_H } = Dimensions.get('window');

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000/identify';
const IMAGE_API_URL = process.env.EXPO_PUBLIC_API_URL ? `${process.env.EXPO_PUBLIC_API_URL}/identify/image` : 'http://localhost:8000/identify/image';

// ── Types ────────────────────────────────────────────────────

type AppState = 'idle' | 'listening' | 'processing' | 'result' | 'nomatch' | 'error';
type Tab = 'home' | 'library' | 'watchlist';

interface StreamingPlatform {
  platform: string;
  deep_link: string;
}

interface MatchResult {
  movie: string;
  year: number;
  confidence: number;
  poster_url?: string;
  backdrop_url?: string;
  logo_url?: string;
  synopsis?: string;
  rating?: number;
  genres?: string[];
  streaming: StreamingPlatform[];
}

interface HistoryItem extends MatchResult {
  foundAt: number; // Date.now() timestamp
}

// ── Date grouping ────────────────────────────────────────────

function groupByDate(items: HistoryItem[]): { label: string; items: HistoryItem[] }[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterday = today - 86_400_000;
  const weekAgo = today - 6 * 86_400_000;

  const groups = new Map<string, HistoryItem[]>();

  for (const item of items) {
    const d = new Date(item.foundAt);
    const dayStart = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

    let label: string;
    if (dayStart === today) label = 'Today';
    else if (dayStart === yesterday) label = 'Yesterday';
    else if (dayStart >= weekAgo) label = d.toLocaleDateString('en-US', { weekday: 'long' });
    else label = d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

    if (!groups.has(label)) groups.set(label, []);
    groups.get(label)!.push(item);
  }

  return Array.from(groups.entries()).map(([label, data]) => ({ label, items: data }));
}

// ── App ──────────────────────────────────────────────────────

export default function App() {
  const [appState, setAppState]     = useState<AppState>('idle');
  const [result, setResult]         = useState<MatchResult | null>(null);
  const [modalVisible, setModal]    = useState(false);
  const [history, setHistory]       = useState<HistoryItem[]>([]);
  const [watchlist, setWatchlist]   = useState<MatchResult[]>([]);
  const [activeTab, setActiveTab]   = useState<Tab>('home');
  const recordingRef                = useRef<Audio.Recording | null>(null);
  const autoStopRef                 = useRef<ReturnType<typeof setTimeout> | null>(null);


  // ── Notification permission ──────────────────────────────
  useEffect(() => {
    Notifications.requestPermissionsAsync();
  }, []);

  const topLabel = {
    idle:       'Tap to Cipher',
    listening:  'Listening...',
    processing: 'Finding movie...',
    result:     'Tap to Cipher',
    nomatch:    'No movie found',
    error:      'Something went wrong',
  }[appState];

  // ── Watchlist helpers ───────────────────────────────────

  function isInWatchlist(movie: string) {
    return watchlist.some(w => w.movie === movie);
  }

  function toggleWatchlist(item: MatchResult) {
    setWatchlist(prev =>
      prev.some(w => w.movie === item.movie)
        ? prev.filter(w => w.movie !== item.movie)
        : [...prev, item],
    );
  }

  // ── Permission ───────────────────────────────────────────

  async function requestMicPermission(): Promise<boolean> {
    const { status } = await Audio.requestPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert(
        'Microphone Permission',
        'Cipher needs microphone access to identify movies. Enable it in Settings.',
        [{ text: 'OK' }],
      );
      return false;
    }
    return true;
  }

  // ── Recording ────────────────────────────────────────────

  async function startRecording() {
    try {
      if (!(await requestMicPermission())) return;

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
        staysActiveInBackground: true,
        interruptionModeIOS: 2,
        shouldDuckAndroid: false,
        interruptionModeAndroid: 1,
      });

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
      );
      recordingRef.current = recording;
      await AudioSessionModule.configure();
      setAppState('listening');
      autoStopRef.current = setTimeout(stopRecording, 15_000);
    } catch (err) {
      console.error('startRecording error:', err);
      setAppState('error');
      setTimeout(() => setAppState('idle'), 2000); 
    }
  }

  async function stopRecording() {
    try {
      if (autoStopRef.current) {
        clearTimeout(autoStopRef.current);
        autoStopRef.current = null;
      }

      const recording = recordingRef.current;
      if (!recording) return;
      recordingRef.current = null;

      await recording.stopAndUnloadAsync();
      await Audio.setAudioModeAsync({ allowsRecordingIOS: false });

      const uri = recording.getURI();
      console.log('Recording URI:', uri);
      if (!uri) throw new Error('Recording URI is null');

      await identifyMovie(uri);
    } catch (err) {
      console.error('stopRecording error:', err);
      setAppState('error');
      setTimeout(() => setAppState('idle'), 2000);
    }
  }

  // ── API call ─────────────────────────────────────────────

  async function identifyMovie(uri: string) {
    setAppState('processing');

    // Keep app alive in background while we upload + wait for result
    await AudioSessionModule.beginBackgroundTask();

    try {
      const formData = new FormData();
      formData.append('audio', {
        uri,
        name: 'recording.m4a',
        type: 'audio/mp4',
      } as any);

      const resp = await fetch(API_URL, {
        method: 'POST',
        body: formData,
      });

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const data = await resp.json();

      if (data.match === false || !data.movie) {
        setAppState('nomatch');
        setTimeout(() => setAppState('idle'), 2000);
        return;
      }

      const matched = data as MatchResult;
      setResult(matched);
      setHistory(prev => {
        const filtered = prev.filter(h => h.movie !== matched.movie);
        return [{ ...matched, foundAt: Date.now() }, ...filtered].slice(0, 50);
      });
      setAppState('result');
      setModal(true);

      // System notification (visible even when on another app)
      Notifications.scheduleNotificationAsync({
        content: {
          title: matched.movie,
          body: `${matched.year} · ${matched.confidence.toFixed(0)}% match`,
          data: matched as unknown as Record<string, unknown>,
        },
        trigger: null,
      });

    } catch (err) {
      console.error('identify error:', err);
      setAppState('error');
      setTimeout(() => setAppState('idle'), 2000);
    } finally {
      await AudioSessionModule.endBackgroundTask();
    }
  }

  // ── Button tap ───────────────────────────────────────────

  function handleTap() {
    if (appState === 'idle' || appState === 'nomatch' || appState === 'error') {
      startRecording();
    } else if (appState === 'listening') {
      stopRecording();
    }
  }

  async function pickImage() {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission needed', 'Allow photo library access to search by image.');
      return;
    }

    const picked = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.8,
    });

    if (picked.canceled || !picked.assets[0]) return;

    setAppState('processing');
    try {
      const uri = picked.assets[0].uri;
      const formData = new FormData();
      formData.append('image', { uri, name: 'image.jpg', type: 'image/jpeg' } as any);

      const resp = await fetch(IMAGE_API_URL, { method: 'POST', body: formData });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const data = await resp.json();
      if (data.match === false || !data.movie) {
        setAppState('nomatch');
        setTimeout(() => setAppState('idle'), 2000);
        return;
      }

      const matched = data as MatchResult;
      setResult(matched);
      setHistory(prev => {
        const filtered = prev.filter(h => h.movie !== matched.movie);
        return [{ ...matched, foundAt: Date.now() }, ...filtered].slice(0, 50);
      });
      setAppState('result');
      setModal(true);
    } catch (err) {
      console.error('pickImage error:', err);
      setAppState('error');
      setTimeout(() => setAppState('idle'), 2000);
    }
  }


  function closeModal() {
    setModal(false);
    setAppState('idle');
    setResult(null);
  }

  function openDetail(item: MatchResult) {
    setResult(item);
    setModal(true);
  }

  // ── Render ───────────────────────────────────────────────

  return (
    <View style={s.root}>
      <StatusBar style="light" />

      {/* Settings */}
      <TouchableOpacity style={s.settingsBtn}>
        <Ionicons name="ellipsis-horizontal" size={22} color="rgba(255,255,255,0.7)" />
      </TouchableOpacity>

      {/* ── HOME TAB ─────────────────────────────────────── */}
      {activeTab === 'home' && (
        <>
          {/* Center block */}
          <View style={s.centerBlock}>
            <Text style={s.tapLabel}>{topLabel}</Text>

            <TouchableOpacity onPress={handleTap} activeOpacity={0.85}>
              <LinearGradient
                colors={appState === 'listening' ? ['#FF2D2D', '#8B0000'] : ['#E50914', '#8B0000']}
                start={{ x: 0.3, y: 0.3 }}
                end={{ x: 1.0, y: 1.0 }}
                style={[s.circle, appState === 'listening' && s.circleListening]}
              />
            </TouchableOpacity>

            {appState === 'listening' && (
              <Text style={s.stopHint}>Tap to stop</Text>
            )}

            {(appState === 'idle' || appState === 'result') && (
              <View style={s.mediaBtnRow}>
                <TouchableOpacity onPress={pickImage} style={s.imageBtn} activeOpacity={0.7}>
                  <Ionicons name="image-outline" size={20} color="rgba(255,255,255,0.6)" />
                  <Text style={s.imageBtnTxt}>Search by image</Text>
                </TouchableOpacity>
              </View>
            )}

            {appState === 'processing' && (
              <ActivityIndicator color="rgba(255,255,255,0.7)" size="small" style={s.spinner} />
            )}
          </View>

          {/* Recently Found */}
          <View style={s.recentWrap}>
            <Text style={s.recentLabel}>Recently Found</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.cardRow}>
              {history.length === 0 ? (
                <>
                  <PlaceholderCard />
                  <PlaceholderCard />
                  <PlaceholderCard />
                </>
              ) : (
                history.slice(0, 10).map((item, i) => (
                  <TouchableOpacity key={`${item.movie}-${i}`} onPress={() => openDetail(item)} activeOpacity={0.8}>
                    <View style={s.posterCard}>
                      {item.poster_url ? (
                        <Image source={{ uri: item.poster_url }} style={s.posterCardImg} />
                      ) : (
                        <View style={[s.posterCardImg, s.posterCardPlaceholder]}>
                          <Text style={s.posterCardInitial}>{item.movie[0]}</Text>
                        </View>
                      )}
                      <Text style={s.posterCardTitle} numberOfLines={2}>{item.movie}</Text>
                      <Text style={s.posterCardYear}>{item.year}</Text>
                    </View>
                  </TouchableOpacity>
                ))
              )}
            </ScrollView>
          </View>
        </>
      )}

      {/* ── LIBRARY TAB ──────────────────────────────────── */}
      {activeTab === 'library' && (
        <ScrollView style={s.listScreen} contentContainerStyle={s.listContent}>
          <Text style={s.screenTitle}>Library</Text>

          {history.length === 0 ? (
            <View style={s.emptyState}>
              <Ionicons name="musical-notes-outline" size={48} color="rgba(255,255,255,0.15)" />
              <Text style={s.emptyText}>No movies identified yet</Text>
              <Text style={s.emptySubtext}>Tap Cipher to get started</Text>
            </View>
          ) : (
            groupByDate(history).map(group => (
              <View key={group.label} style={s.dateGroup}>
                <Text style={s.dateLabel}>{group.label}</Text>
                {group.items.map((item, i) => (
                  <TouchableOpacity
                    key={`${item.movie}-${i}`}
                    style={s.listRow}
                    onPress={() => openDetail(item)}
                    activeOpacity={0.7}
                  >
                    {item.poster_url ? (
                      <Image source={{ uri: item.poster_url }} style={s.listThumb} />
                    ) : (
                      <View style={[s.listThumb, s.listThumbPlaceholder]}>
                        <Text style={s.listThumbLetter}>{item.movie[0]}</Text>
                      </View>
                    )}
                    <View style={s.listInfo}>
                      <Text style={s.listMovie} numberOfLines={1}>{item.movie}</Text>
                      <Text style={s.listMeta}>
                        {item.year} · {item.confidence.toFixed(0)}% match
                      </Text>
                    </View>
                    <TouchableOpacity onPress={() => toggleWatchlist(item)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
                      <Ionicons
                        name={isInWatchlist(item.movie) ? 'bookmark' : 'bookmark-outline'}
                        size={20}
                        color={isInWatchlist(item.movie) ? '#E50914' : 'rgba(255,255,255,0.3)'}
                      />
                    </TouchableOpacity>
                  </TouchableOpacity>
                ))}
              </View>
            ))
          )}
        </ScrollView>
      )}

      {/* ── WATCHLIST TAB ────────────────────────────────── */}
      {activeTab === 'watchlist' && (
        <ScrollView style={s.listScreen} contentContainerStyle={s.listContent}>
          <Text style={s.screenTitle}>Watchlist</Text>

          {watchlist.length === 0 ? (
            <View style={s.emptyState}>
              <Ionicons name="bookmark-outline" size={48} color="rgba(255,255,255,0.15)" />
              <Text style={s.emptyText}>Your watchlist is empty</Text>
              <Text style={s.emptySubtext}>Save movies to watch later</Text>
            </View>
          ) : (
            watchlist.map((item, i) => (
              <TouchableOpacity
                key={`${item.movie}-${i}`}
                style={s.listRow}
                onPress={() => openDetail(item)}
                activeOpacity={0.7}
              >
                {item.poster_url ? (
                  <Image source={{ uri: item.poster_url }} style={s.listThumb} />
                ) : (
                  <View style={[s.listThumb, s.listThumbPlaceholder]}>
                    <Text style={s.listThumbLetter}>{item.movie[0]}</Text>
                  </View>
                )}
                <View style={s.listInfo}>
                  <Text style={s.listMovie} numberOfLines={1}>{item.movie}</Text>
                  <Text style={s.listMeta}>
                    {item.year}{item.genres && item.genres.length > 0 ? ` · ${item.genres[0]}` : ''}
                  </Text>
                </View>
                <TouchableOpacity onPress={() => toggleWatchlist(item)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
                  <Ionicons name="bookmark" size={20} color="#E50914" />
                </TouchableOpacity>
              </TouchableOpacity>
            ))
          )}
        </ScrollView>
      )}

      {/* ── Tab bar (frosted glass) ──────────────────────── */}
      <View style={s.tabBarWrap}>
        <View style={s.tabBar}>
          <TouchableOpacity style={s.tabItem} onPress={() => setActiveTab('home')}>
            <LinearGradient
              colors={activeTab === 'home' ? ['#E50914', '#8B0000'] : ['#333', '#333']}
              style={s.tabDot}
            />
            <Text style={[s.tabLabel, activeTab === 'home' ? s.tabLabelActive : s.tabLabelInactive]}>Home</Text>
          </TouchableOpacity>

          <TouchableOpacity style={s.tabItem} onPress={() => setActiveTab('library')}>
            <Ionicons
              name={activeTab === 'library' ? 'albums' : 'albums-outline'}
              size={22}
              color={activeTab === 'library' ? '#fff' : 'rgba(255,255,255,0.4)'}
            />
            <Text style={[s.tabLabel, activeTab === 'library' ? s.tabLabelActive : s.tabLabelInactive]}>Library</Text>
          </TouchableOpacity>

          <TouchableOpacity style={s.tabItem} onPress={() => setActiveTab('watchlist')}>
            <Ionicons
              name={activeTab === 'watchlist' ? 'bookmark' : 'bookmark-outline'}
              size={20}
              color={activeTab === 'watchlist' ? '#fff' : 'rgba(255,255,255,0.4)'}
            />
            <Text style={[s.tabLabel, activeTab === 'watchlist' ? s.tabLabelActive : s.tabLabelInactive]}>Watchlist</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* ── Result Modal (full-screen, Apple TV style) ────── */}
      <Modal
        visible={modalVisible}
        transparent={false}
        animationType="slide"
        onRequestClose={closeModal}
      >
        <View style={s.modalRoot}>
          {/* Close button */}
          <TouchableOpacity style={s.modalClose} onPress={closeModal}>
            <Ionicons name="chevron-back" size={26} color="#fff" />
          </TouchableOpacity>

          <ScrollView
            showsVerticalScrollIndicator={false}
            contentContainerStyle={s.modalScroll}
            bounces={false}
          >
            {/* Full-screen poster hero — prefer backdrop (no title baked in) */}
            <View style={s.heroWrap}>
              {result?.poster_url ? (
                <Image
                  source={{ uri: result.poster_url }}
                  style={s.heroPoster}
                  resizeMode="cover"
                />
              ) : (
                <View style={[s.heroPoster, { backgroundColor: '#2E2E2E' }]} />
              )}

              {/* Gradient blend into black */}
              <LinearGradient
                colors={['transparent', 'rgba(0,0,0,0.4)', '#000']}
                locations={[0.45, 0.75, 1]}
                style={s.heroGradient}
              />

              {/* Title overlaid at bottom-left of poster */}
              <View style={s.heroTitleWrap}>
                <Text style={s.modalMovie}>{result?.movie}</Text>
              </View>
            </View>

            {/* Meta: Genre · Year · Confidence */}
            <Text style={s.metaLine}>
              {result?.genres && result.genres.length > 0
                ? `${result.genres.join(' · ')}  ·  `
                : ''}
              {result?.year}{`  ·  ${result?.confidence.toFixed(0)}% match`}
            </Text>

            {/* Action row: streaming buttons + save */}
            <View style={s.actionRow}>
              {result && result.streaming.length > 0 ? (
                result.streaming.map((sv) => (
                  <TouchableOpacity
                    key={sv.platform}
                    style={s.actionBtn}
                    onPress={() => Linking.openURL(sv.deep_link)}
                  >
                    <Text style={s.actionBtnTxt}>{sv.platform}</Text>
                  </TouchableOpacity>
                ))
              ) : (
                <View style={s.actionBtnMuted}>
                  <Text style={s.actionBtnMutedTxt}>Not streaming</Text>
                </View>
              )}

              {result && (
                <TouchableOpacity
                  style={s.saveCircle}
                  onPress={() => toggleWatchlist(result)}
                >
                  <Ionicons
                    name={isInWatchlist(result.movie) ? 'bookmark' : 'bookmark-outline'}
                    size={20}
                    color={isInWatchlist(result.movie) ? '#E50914' : '#fff'}
                  />
                </TouchableOpacity>
              )}
            </View>

            {/* Synopsis */}
            {result?.synopsis && (
              <Text style={s.synopsis}>{result.synopsis}</Text>
            )}
          </ScrollView>
        </View>
      </Modal>
    </View>
  );
}

// ── Placeholder card ─────────────────────────────────────────

function PlaceholderCard() {
  return (
    <View style={s.posterCard}>
      <View style={[s.posterCardImg, s.posterCardPlaceholder]} />
      <View style={{ height: 10, borderRadius: 5, backgroundColor: '#2E2E2E', width: 80, marginTop: 8 }} />
      <View style={{ height: 8, borderRadius: 4, backgroundColor: '#2E2E2E', width: 50, marginTop: 5 }} />
    </View>
  );
}

// ── Styles ───────────────────────────────────────────────────

const TAB_H    = 64;
const BTN_SIZE = 180;
const CARD_W   = 110;
const CARD_H   = 165;

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#000' },

  settingsBtn: { position: 'absolute', top: 56, right: 20, zIndex: 10, padding: 6 },

  // ── Home ──
  centerBlock: {
    position: 'absolute',
    top: 0, bottom: 0, left: 0, right: 0,
    alignItems: 'center',
    justifyContent: 'center',
    paddingBottom: 220,
    gap: 28,
  },
  tapLabel: { fontSize: 22, fontWeight: '700', color: '#fff', textAlign: 'center' },

  circle: {
    width: BTN_SIZE,
    height: BTN_SIZE,
    borderRadius: BTN_SIZE / 2,
  },
  circleListening: {
    borderWidth: 3,
    borderColor: 'rgba(255,255,255,0.6)',
  },

  stopHint: { fontSize: 13, color: 'rgba(255,255,255,0.55)', marginTop: -14 },
  spinner: { marginTop: -14 },

  recentWrap: { position: 'absolute', bottom: 30 + TAB_H + 16, left: 0, right: 0 },
  recentLabel: { fontSize: 15, fontWeight: '600', color: '#fff', marginLeft: 20, marginBottom: 12 },
  cardRow: { paddingLeft: 20, paddingRight: 8, gap: 12 },

  posterCard: { width: CARD_W, alignItems: 'center' },
  posterCardImg: { width: CARD_W, height: CARD_H, borderRadius: 10 },
  posterCardPlaceholder: { backgroundColor: '#2E2E2E', alignItems: 'center', justifyContent: 'center' },
  posterCardInitial: { fontSize: 32, color: 'rgba(255,255,255,0.3)', fontWeight: '700' },
  posterCardTitle: { fontSize: 11, color: '#fff', fontWeight: '600', textAlign: 'center', marginTop: 7, width: CARD_W },
  posterCardYear: { fontSize: 10, color: 'rgba(255,255,255,0.4)', marginTop: 2 },

  // ── Library / Watchlist list screens ──
  listScreen: { flex: 1, paddingTop: 50 },
  listContent: { paddingTop: 20, paddingHorizontal: 20, paddingBottom: TAB_H + 50 },
  screenTitle: { fontSize: 32, fontWeight: '800', color: '#fff', marginBottom: 24 },

  emptyState: { alignItems: 'center', marginTop: 80, gap: 10 },
  emptyText: { fontSize: 17, color: 'rgba(255,255,255,0.5)', fontWeight: '600' },
  emptySubtext: { fontSize: 13, color: 'rgba(255,255,255,0.25)' },

  dateGroup: { marginBottom: 24 },
  dateLabel: { fontSize: 13, fontWeight: '700', color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 12 },

  listRow: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 14, padding: 10, marginBottom: 8,
  },
  listThumb: { width: 50, height: 72, borderRadius: 8 },
  listThumbPlaceholder: { backgroundColor: '#2E2E2E', alignItems: 'center', justifyContent: 'center' },
  listThumbLetter: { fontSize: 20, color: 'rgba(255,255,255,0.25)', fontWeight: '700' },
  listInfo: { flex: 1, marginLeft: 12, gap: 3 },
  listMovie: { fontSize: 15, fontWeight: '600', color: '#fff' },
  listMeta: { fontSize: 12, color: 'rgba(255,255,255,0.4)' },

  // ── Tab bar ──
  tabBarWrap: {
    position: 'absolute', bottom: 30, left: 24, right: 24,
    borderRadius: 32, overflow: 'hidden',
    borderWidth: 0.5, borderColor: 'rgba(255,255,255,0.18)',
  },
  tabBar: {
    flexDirection: 'row', alignItems: 'center',
    height: TAB_H, paddingHorizontal: 8,
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  tabItem: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 4 },
  tabDot: { width: 22, height: 22, borderRadius: 11 },
  tabLabel: { fontSize: 10, fontWeight: '500' },
  tabLabelActive: { color: '#fff' },
  tabLabelInactive: { color: 'rgba(255,255,255,0.4)' },

  // ── Modal (full-screen, Apple TV style) ──
  modalRoot: { flex: 1, backgroundColor: '#000' },
  modalClose: {
    position: 'absolute', top: 54, left: 16, zIndex: 10,
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: 'rgba(0,0,0,0.45)',
    alignItems: 'center', justifyContent: 'center',
  },
  modalScroll: { paddingBottom: 50 },

  heroWrap: {
    width: '100%',
    height: SCREEN_H * 0.70,
  },
  heroPoster: {
    width: '100%',
    height: '100%',
  },
  heroGradient: {
    position: 'absolute',
    bottom: 0, left: 0, right: 0,
    height: '55%',
  },
  heroTitleWrap: {
    position: 'absolute',
    bottom: 24, left: 24, right: 24,
    alignItems: 'flex-start',
  },
  modalMovie: { fontSize: 28, fontWeight: '800', color: '#fff', textAlign: 'left', textShadowColor: 'rgba(0,0,0,0.9)', textShadowOffset: { width: 0, height: 2 }, textShadowRadius: 8 },

  metaLine: { fontSize: 13, color: 'rgba(255,255,255,0.45)', textAlign: 'center', marginTop: 12, marginBottom: 20 },

  actionRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 10, paddingHorizontal: 24, marginBottom: 20,
  },
  actionBtn: {
    flex: 1, backgroundColor: '#fff', borderRadius: 14,
    paddingVertical: 14, alignItems: 'center',
  },
  actionBtnTxt: { color: '#000', fontWeight: '700', fontSize: 15 },
  actionBtnMuted: {
    flex: 1, backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: 14,
    paddingVertical: 14, alignItems: 'center',
  },
  actionBtnMutedTxt: { color: 'rgba(255,255,255,0.35)', fontWeight: '600', fontSize: 14 },
  saveCircle: {
    width: 50, height: 50, borderRadius: 25,
    backgroundColor: 'rgba(255,255,255,0.1)',
    alignItems: 'center', justifyContent: 'center',
  },

  synopsis: { fontSize: 14, color: 'rgba(255,255,255,0.55)', lineHeight: 21, paddingHorizontal: 24, marginBottom: 20 },

  mediaBtnRow: { flexDirection: 'row', gap: 10 },
  imageBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 10, paddingHorizontal: 20, borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.08)' },
  imageBtnTxt: { fontSize: 13, color: 'rgba(255,255,255,0.6)', fontWeight: '500' },
});
