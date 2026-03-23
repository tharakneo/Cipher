import { Audio } from 'expo-av';
import { LinearGradient } from 'expo-linear-gradient';
import { StatusBar } from 'expo-status-bar';
import { useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Dimensions,
  Linking,
  Modal,
  PanResponder,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  TouchableWithoutFeedback,
  View,
} from 'react-native';

const { width: W, height: H } = Dimensions.get('window');

const API_URL = 'http://192.168.0.142:8000/identify';

// ── Types ────────────────────────────────────────────────────

type AppState = 'idle' | 'listening' | 'processing' | 'result' | 'nomatch' | 'error';

interface StreamingPlatform {
  platform: string;
  deep_link: string;
}

interface MatchResult {
  movie: string;
  year: number;
  confidence: number;
  streaming: StreamingPlatform[];
}

// ── App ──────────────────────────────────────────────────────

export default function App() {
  const [appState, setAppState]     = useState<AppState>('idle');
  const [result, setResult]         = useState<MatchResult | null>(null);
  const [modalVisible, setModal]    = useState(false);
  const recordingRef                = useRef<Audio.Recording | null>(null);
  const autoStopRef                 = useRef<ReturnType<typeof setTimeout> | null>(null);

  const topLabel = {
    idle:       'Tap to Cipher',
    listening:  'Listening...',
    processing: 'Finding movie...',
    result:     'Tap to Cipher',
    nomatch:    'No movie found',
    error:      'Something went wrong',
  }[appState];

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
      });

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
      );
      recordingRef.current = recording;
      setAppState('listening');
      autoStopRef.current = setTimeout(stopRecording, 30_000);
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

    try {
      const formData = new FormData();
      formData.append('audio', {
        uri,
        name: 'recording.m4a',
        type: 'audio/m4a',
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

      setResult(data as MatchResult);
      setAppState('result');
      setModal(true);

    } catch (err) {
      console.error('identify error:', err);
      setAppState('error');
      setTimeout(() => setAppState('idle'), 2000);
    }
  }

  // ── Button tap ───────────────────────────────────────────

  function handleTap() {
    if (appState === 'idle' || appState === 'nomatch' || appState === 'error') {
      startRecording();
    } else if (appState === 'listening') {
      stopRecording();
    }
    // ignore taps during processing
  }

  function closeModal() {
    setModal(false);
    setAppState('idle');
    setResult(null);
  }

  // ── Swipe-down pan responder for modal ───────────────────
  const panResponder = useRef(
    PanResponder.create({
      onMoveShouldSetPanResponder: (_, g) => g.dy > 10,
      onPanResponderRelease: (_, g) => { if (g.dy > 60) closeModal(); },
    }),
  ).current;

  // ── Render ───────────────────────────────────────────────

  return (
    <View style={s.root}>
      <StatusBar style="light" />

      {/* Gear */}
      <TouchableOpacity style={s.gear}>
        <Text style={s.gearTxt}>⚙</Text>
      </TouchableOpacity>

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

        {/* "Tap to stop" hint */}
        {appState === 'listening' && (
          <Text style={s.stopHint}>Tap to stop</Text>
        )}

        {/* Spinner while processing */}
        {appState === 'processing' && (
          <ActivityIndicator color="rgba(255,255,255,0.7)" size="small" style={s.spinner} />
        )}
      </View>

      {/* Recently Found */}
      <View style={s.recentWrap}>
        <Text style={s.recentLabel}>Recently Found</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.cardRow}>
          <PlaceholderCard />
          <PlaceholderCard />
          <PlaceholderCard />
        </ScrollView>
      </View>

      {/* Tab bar */}
      <View style={s.tabBar}>
        <View style={s.pill}>
          <TouchableOpacity style={[s.tabItem, s.tabItemActive]}>
            <Text style={s.tabIconActive}>⌂</Text>
            <Text style={[s.tabLabel, s.tabLabelActive]}>Home</Text>
          </TouchableOpacity>
          <TouchableOpacity style={s.tabItem}>
            <Text style={s.tabIconInactive}>▤</Text>
            <Text style={[s.tabLabel, s.tabLabelInactive]}>Library</Text>
          </TouchableOpacity>
        </View>
        <TouchableOpacity style={s.searchCircle}>
          <Text style={s.searchIcon}>⌕</Text>
        </TouchableOpacity>
      </View>

      {/* ── Result Modal ──────────────────────────────────── */}
      <Modal
        visible={modalVisible}
        transparent
        animationType="slide"
        onRequestClose={closeModal}
      >
        <TouchableWithoutFeedback onPress={closeModal}>
          <View style={s.modalOverlay}>
            <TouchableWithoutFeedback>
              <View style={s.modalSheet} {...panResponder.panHandlers}>
                {/* Drag handle */}
                <View style={s.dragHandle} />

                <Text style={s.modalMovie}>{result?.movie}</Text>
                <Text style={s.modalYear}>{result?.year}</Text>
                <Text style={s.modalConfidence}>
                  {result?.confidence.toFixed(0)}% match
                </Text>

                {result && result.streaming.length > 0 ? (
                  <View style={s.streamingWrap}>
                    <Text style={s.streamingTitle}>Watch on</Text>
                    <View style={s.streamingRow}>
                      {result.streaming.map((s) => (
                        <TouchableOpacity
                          key={s.platform}
                          style={st.platformBtn}
                          onPress={() => Linking.openURL(s.deep_link)}
                        >
                          <Text style={st.platformTxt}>{s.platform}</Text>
                        </TouchableOpacity>
                      ))}
                    </View>
                  </View>
                ) : (
                  <Text style={s.noStreaming}>Not streaming in your region</Text>
                )}
              </View>
            </TouchableWithoutFeedback>
          </View>
        </TouchableWithoutFeedback>
      </Modal>
    </View>
  );
}

// ── Placeholder card ─────────────────────────────────────────

function PlaceholderCard() {
  return (
    <View style={s.card}>
      <View style={s.cardThumb} />
      <View style={s.cardText}>
        <View style={s.cardLineLong} />
        <View style={s.cardLineShort} />
      </View>
    </View>
  );
}

// ── Styles ───────────────────────────────────────────────────

const PILL_H   = 58;
const BTN_SIZE = 180;

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#000' },

  gear: { position: 'absolute', top: 56, right: 20, zIndex: 10, padding: 4 },
  gearTxt: { fontSize: 22, color: '#fff' },

  centerBlock: {
    position: 'absolute',
    top: 0, bottom: 0, left: 0, right: 0,
    alignItems: 'center',
    justifyContent: 'center',
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

  stopHint: {
    fontSize: 13,
    color: 'rgba(255,255,255,0.55)',
    marginTop: -14,
  },
  spinner: { marginTop: -14 },

  recentWrap: { position: 'absolute', bottom: 36 + PILL_H + 20, left: 0, right: 0 },
  recentLabel: { fontSize: 15, fontWeight: '600', color: '#fff', marginLeft: 20, marginBottom: 12 },
  cardRow: { paddingLeft: 20, paddingRight: 8 },
  card: {
    flexDirection: 'row', alignItems: 'center',
    width: W - 60, backgroundColor: '#1A1A1A',
    borderRadius: 12, padding: 12, marginRight: 10,
  },
  cardThumb: { width: 52, height: 52, borderRadius: 8, backgroundColor: '#2E2E2E', marginRight: 12, flexShrink: 0 },
  cardText: { flex: 1, gap: 8 },
  cardLineLong: { height: 12, borderRadius: 6, backgroundColor: '#2E2E2E', width: '80%' },
  cardLineShort: { height: 10, borderRadius: 5, backgroundColor: '#2E2E2E', width: '55%' },

  tabBar: { position: 'absolute', bottom: 36, left: 20, right: 20, flexDirection: 'row', alignItems: 'center', gap: 10 },
  pill: { flex: 1, flexDirection: 'row', height: PILL_H, borderRadius: PILL_H / 2, backgroundColor: 'rgba(255,255,255,0.10)', overflow: 'hidden' },
  tabItem: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 3 },
  tabItemActive: { backgroundColor: 'rgba(255,255,255,0.18)', borderRadius: PILL_H / 2 },
  tabIconActive:    { fontSize: 18, color: '#fff' },
  tabIconInactive:  { fontSize: 18, color: 'rgba(255,255,255,0.45)' },
  tabLabel:         { fontSize: 10, fontWeight: '500' },
  tabLabelActive:   { color: '#fff' },
  tabLabelInactive: { color: 'rgba(255,255,255,0.45)' },
  searchCircle: { width: PILL_H, height: PILL_H, borderRadius: PILL_H / 2, backgroundColor: 'rgba(255,255,255,0.10)', alignItems: 'center', justifyContent: 'center' },
  searchIcon: { fontSize: 22, color: '#fff', transform: [{ scaleX: -1 }] },

  // Modal
  modalOverlay: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.5)' },
  modalSheet: {
    backgroundColor: '#1A1A1A',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: 24,
    paddingBottom: 48,
    paddingTop: 12,
    alignItems: 'center',
  },
  dragHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.2)', marginBottom: 24 },
  modalMovie: { fontSize: 26, fontWeight: '800', color: '#fff', textAlign: 'center', marginBottom: 6 },
  modalYear:  { fontSize: 15, color: 'rgba(255,255,255,0.5)', marginBottom: 8 },
  modalConfidence: { fontSize: 13, color: '#E50914', fontWeight: '600', marginBottom: 28 },
  streamingWrap: { width: '100%' },
  streamingTitle: { fontSize: 13, color: 'rgba(255,255,255,0.45)', marginBottom: 12, textAlign: 'center' },
  streamingRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, justifyContent: 'center' },
  noStreaming: { fontSize: 14, color: 'rgba(255,255,255,0.4)', textAlign: 'center' },
});

// Streaming button styles (separate to avoid name clash with 's')
const st = StyleSheet.create({
  platformBtn: {
    backgroundColor: '#E50914',
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 12,
  },
  platformTxt: { color: '#fff', fontWeight: '700', fontSize: 14 },
});
