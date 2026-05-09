# Fish Drying Predictor — Flutter Frontend

Flutter client for the **TimeAndSpoilagePredictionService** FastAPI microservice.

## Project structure

```
Frontend/
├── pubspec.yaml
├── analysis_options.yaml
└── lib/
    ├── main.dart
    ├── models/
    │   └── prediction_models.dart   # Request/response DTOs
    ├── services/
    │   └── api_service.dart         # HTTP client wrapping the 3 endpoints
    ├── providers/
    │   └── prediction_provider.dart # ChangeNotifier holding results + load state
    └── screens/
        └── home_screen.dart         # Landing screen with feature tiles (TODO: wire navigation)
```

## First-time setup

The Android/iOS platform folders aren't checked in. Generate them once:

```bash
cd Frontend
flutter create . --platforms=android,ios --org com.sliit.r26
flutter pub get
```

`flutter create .` is non-destructive — it preserves existing `lib/`, `pubspec.yaml`, etc. and only fills in missing platform/configuration files.

## Backend base URL

`lib/main.dart` defaults to `http://10.0.2.2:8001` (Android emulator's loopback to host).

| Run target | Use |
|---|---|
| Android emulator | `http://10.0.2.2:8001` |
| iOS simulator | `http://localhost:8001` |
| Physical device | `http://<your-machine-LAN-ip>:8001` |

Make sure the FastAPI service is running (`uvicorn app.main:app --port 8001` from `Backend/src/TimeAndSpoilagePredictionService/`).

## Running

```bash
flutter run
```

## What's stubbed vs. what's still to do

**Stubbed (working):**
- API client for all 3 endpoints (drying-time / spoilage-risk / recommendation)
- Provider holding load state and results
- Home screen with feature tiles

**Still to do (manual implementations):**
- Form screens for each prediction (input fields → call provider → show result)
- Navigation wiring in `home_screen.dart` `onTap` callbacks
- Result/detail screens
- Error UI surfacing `provider.errorMessage`
- Tests in `test/`
