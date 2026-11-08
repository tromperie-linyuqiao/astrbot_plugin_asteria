# Offline speech dependencies

Phone mode uses the unmodified **sherpa-onnx 2.0.1** pure Java API and Android JNI runtime from [k2-fsa's official release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1). These are third-party components, not original project code. The APK retains Apache-2.0 and Microsoft ONNX Runtime license notices in its raw resources. The AAR's Kotlin API classes are excluded; the matching pure Java API is included. The APK carries arm64-v8a, armeabi-v7a, x86 and x86_64 native libraries. The x86 AAR also requires its included libonnxruntime.so.

Pinned artifacts:

- `sherpa-onnx-jvm-2.0.1.jar`, 192880 bytes, SHA256 `8320e2457b6e38dd624fb619d3552e11ef78ffeb394622056126b16f2fd99d12`.
- `sherpa-onnx-static-link-onnxruntime-2.0.1.aar`, 38577050 bytes, SHA256 `07e042d97f3a6bd5b7fe74d4eef0513dc01a714b16c15a903250095aba43a575`.

Run `python prepare_speech_dependencies.py --download` explicitly, or place those exact files in the directory selected with the builder's `--speech-deps`. The APK builder freezes and verifies them and does not use the network. Dependencies and models are not checked into source control. Native libraries are compressed in the APK and explicitly extracted by Android at install time.

The separately imported **SenseVoiceSmall** int8 export is by **Alibaba Group / FunAudioLLM and contributors**, converted for sherpa-onnx as `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17`. Original model: https://huggingface.co/FunAudioLLM/SenseVoiceSmall ; export: https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models . Model weights have their own **FunASR Model Open Source License Agreement v1.1** and are not licensed by the sherpa-onnx Apache license.

Use `python prepare_voice_model.py MODEL_DIRECTORY --output MODEL.zip` to package the pinned model, tokens and their original LICENSE, MODEL_LICENSE.txt and README.md. Transfer that ZIP to the phone and choose “导入离线语音模型”. The model is not bundled into the APK or silently downloaded. Import checks exact size and SHA256 and writes only the two fixed model files into app-private, non-backup storage. It does not start recording or read user audio.

Phone mode starts only after a visible user action and microphone permission. The microphone foreground service, its mute/end controls and a partial wake lock support an explicitly ongoing call; there is no boot start or process-death resume. Recordings stay in bounded memory and are cleared after transcription or cancellation. Recognized text is sent as ordinary chat only during the explicitly started call, using the original account/session/sender and stable receipt protection. TTS generation is separate and is not enabled by phone mode. A playback gate is available to stop capture while app voice output plays.

Physical microphone quality, battery/thermal behavior and OEM lock-screen behavior require device acceptance; desktop JNI and browser fixtures do not establish those results.
