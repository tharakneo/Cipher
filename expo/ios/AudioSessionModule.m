#import <React/RCTBridgeModule.h>
#import <AVFoundation/AVFoundation.h>
#import <UIKit/UIKit.h>

@interface AudioSessionModule : NSObject <RCTBridgeModule>
@property (nonatomic, assign) UIBackgroundTaskIdentifier bgTask;
@end

@implementation AudioSessionModule

RCT_EXPORT_MODULE();

- (instancetype)init {
  self = [super init];
  if (self) {
    _bgTask = UIBackgroundTaskInvalid;
  }
  return self;
}

RCT_EXPORT_METHOD(configure:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject)
{
  NSError *error = nil;
  AVAudioSession *session = [AVAudioSession sharedInstance];

  [session setCategory:AVAudioSessionCategoryPlayAndRecord
           withOptions:AVAudioSessionCategoryOptionMixWithOthers | AVAudioSessionCategoryOptionDefaultToSpeaker
                 error:&error];

  if (error) {
    reject(@"audio_session_error", error.localizedDescription, error);
    return;
  }

  [session setActive:YES error:&error];

  if (error) {
    reject(@"audio_session_error", error.localizedDescription, error);
    return;
  }

  resolve(nil);
}

RCT_EXPORT_METHOD(beginBackgroundTask:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject)
{
  dispatch_async(dispatch_get_main_queue(), ^{
    self.bgTask = [[UIApplication sharedApplication] beginBackgroundTaskWithName:@"CipherIdentify"
                                                               expirationHandler:^{
      [[UIApplication sharedApplication] endBackgroundTask:self.bgTask];
      self.bgTask = UIBackgroundTaskInvalid;
    }];
    resolve(nil);
  });
}

RCT_EXPORT_METHOD(endBackgroundTask:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject)
{
  dispatch_async(dispatch_get_main_queue(), ^{
    if (self.bgTask != UIBackgroundTaskInvalid) {
      [[UIApplication sharedApplication] endBackgroundTask:self.bgTask];
      self.bgTask = UIBackgroundTaskInvalid;
    }
    resolve(nil);
  });
}

@end
