# CCTV Automated Face Recognition Attendance System
## Complete System Architecture, Technical Details, Features, & Operational Guide

---

## 📌 Executive Summary

The **CCTV Automated Face Recognition Attendance System** is an end-to-end computer vision and deep learning solution designed for educational institutions. The system automatically records student attendance by processing video recordings from classroom CCTV cameras. 

By employing a **dual-branch feature extraction architecture** (combining AdaFace CNN and Swin Vision Transformer), real-time face detection with landmark alignment (RetinaFace), and vector-based similarity matching, the system eliminates proxy attendance, reduces administrative overhead, and provides instant attendance decision reporting (Excel & PDF export).

---

## 🛠️ Tech Stack & Dependencies

### **Backend (Python / Flask & Deep Learning Stack)**
| Category | Technology / Library | Purpose / Usage |
| :--- | :--- | :--- |
| **Web Framework** | Python 3, Flask | Lightweight REST API backend |
| **Database & ORM** | Flask-SQLAlchemy, SQLite (`cctv_attendance.db`), Flask-Migrate | Relational schema management and migrations |
| **Authentication & Security** | Flask-Bcrypt, Flask-JWT-Extended | Role-based Access Control (Faculty & HOD), password hashing, JWT bearer tokens |
| **CORS & Environment** | Flask-CORS, python-dotenv | Cross-origin resource sharing and environment management |
| **Face Detection & Alignment** | InsightFace (RetinaFace / `buffalo_l`), OpenCV, scikit-image | 5-point facial landmark alignment to 112×112 canonical ArcFace crops; Haar Cascade fallback |
| **Face Recognition Models** | PyTorch, Torchvision, TIMM, AdaFace (IR-101), Swin Transformer (`swin_tiny_patch4_window7_224`), DeepFace (FaceNet512 / ArcFace fallback) | Dual-branch feature embedding generation (512-D descriptors) |
| **Vector Matching & Math** | NumPy, SciPy | Cosine similarity calculation via vectorized matrix operations |
| **Reporting & Utilities** | openpyxl, reportlab, Pillow | Generating structured `.xlsx` workbooks and custom formatted `.pdf` reports |

### **Frontend (Modern Web UI Stack)**
| Category | Technology / Library | Purpose / Usage |
| :--- | :--- | :--- |
| **Build Tool & Framework** | React 18, Vite 6 | Fast single-page application bundling |
| **Routing** | React Router DOM v7 | Dynamic client-side routing (`/login`, `/dashboard`, `/classes/:id`, `/attendance/:id`) |
| **Styling & UI Components** | Tailwind CSS v3, PostCSS, Autoprefixer, Radix UI Primitives (`@radix-ui/react-slot`, `@radix-ui/react-switch`) | Custom institutional UI design system with dark/red SPIT color palette |
| **Icons & Motion** | Lucide React, React Icons, Framer Motion | Modern iconography and smooth UI micro-animations |
| **Notifications & Data Visualization** | Sonner, Recharts | Interactive toast notifications and visual charts |
| **Progressive Web App** | Vite PWA Plugin | PWA assets and offline service worker preparation |

---

## 🧠 System Architecture & Processing Pipeline

The system processes video feeds through an **8-step pipeline**:

```
[ CCTV Video Upload ]
        │
        ▼
[ 1. Video Ingest ]
        │
        ▼
[ 2. Frame Sampling ] (Interval: e.g. every 2.0s)
        │
        ▼
[ 3. Face Detection & Landmark Alignment ] (RetinaFace -> 112x112 Crop)
        │
        ├───► Branch 4a: AdaFace (IR-101 CNN) ──────────► [ 512-D Embedding ] ──┐
        │                                                                        │
        └───► Branch 4b: Swin Transformer (Swin-T) ─────► [ 512-D Embedding ] ──┴─► [ 5. Feature Fusion ] (Concat 1024-D -> MLP -> 512-D)
                                                                                                 │
                                                                                                 ▼
                                                                                   [ 6. Vector Cosine Matching ] (Enrolled DB Matrix)
                                                                                                 │
                                                                                                 ▼
                                                                                   [ 7. First-Appearance Tracking & Decision Logic ]
                                                                                                 │
                                                                                                 ▼
                                                                                   [ 8. Report Generation (XLSX/PDF) & Notifications ]
```

### Detailed Pipeline Breakdown:

1. **Video Ingestion**: Supports `.mp4`, `.avi`, `.mov`, `.mkv` files. Uploaded files are stored in `storage/videos/` with unique UUID names.
2. **Frame Sampling**: Extracts video frames at a configurable sampling rate (default `2.0` seconds). Reduces computational overhead while ensuring student entries are captured.
3. **Face Detection & Landmark Alignment**:
   - Uses **InsightFace RetinaFace** detector (`buffalo_l`).
   - Extracts 5 facial landmarks (eyes, nose, mouth corners).
   - Computes similarity transformation matrix (`skimage.transform.SimilarityTransform`) to warp facial crops into 112×112 BGR canonical ArcFace orientation.
   - Robust fallback cascade: If RetinaFace fails or dependencies are missing, falls back to OpenCV Haar Cascade, and finally full-frame/bounding-box cropping.
4. **Dual-Branch Face Recognition**:
   - **AdaFace Branch**: Quality-adaptive IR-101 CNN backbone producing a 512-D L2-normalized feature vector.
   - **Swin Transformer Branch**: Swin-Tiny Vision Transformer (`swin_tiny_patch4_window7_224`) using global self-attention with a projection head to produce a 512-D feature vector.
5. **Feature Fusion (`EmbeddingFusion`)**:
   - Concatenates AdaFace (512-D) + Swin Transformer (512-D) features into a 1024-D vector.
   - Passes through a learned 2-layer MLP (`FusionFC`: Linear 1024->512 -> BatchNorm1d -> ReLU -> Linear 512->512) and applies L2-normalization to yield a unified 512-D descriptor.
6. **Vector Similarity Matching (`match_face`)**:
   - Constructs an $(N, 512)$ matrix of enrolled student embeddings.
   - Computes cosine similarity scores using vectorized matrix multiplication ($Q_{\text{norm}} \times DB_{\text{norm}}^T$).
   - Matches if similarity score $\ge \text{threshold}$ (default `0.55`).
7. **First-Appearance Tracking & Attendance Decision**:
   - `FirstAppearanceTracker` tracks the earliest timestamp (in seconds) each student appears in the video feed.
   - **Early Exit Optimization**: If 100% of enrolled students are identified before the video ends, processing stops immediately.
   - **Decision Logic**:
     - **Present**: First seen timestamp $\le$ Class Grace Period (e.g. 10 minutes).
     - **Late-Absent**: First seen timestamp $>$ Grace Period.
     - **Absent**: Student was never detected in the video.
8. **Report Generation**:
   - Generates formatted Excel spreadsheets (`.xlsx`) with status color coding (Green = Present, Orange = Late-Absent, Red = Absent).
   - Generates professional PDF reports (`.pdf`) with summary metrics.

---

## ✨ Features List

### 👥 1. Multi-Role User Management & Authentication
- **Faculty Role**:
  - Can create and manage their own classrooms.
  - Can enroll students via bulk ZIP uploads.
  - Can upload CCTV videos and trigger processing.
  - Can download Excel/PDF attendance reports.
- **HOD (Head of Department) Role**:
  - Has administrative access over all classrooms across all faculty members (`HOD_SEES_ALL=true`).
  - Ability to register new Faculty members directly from the dashboard.
- **JWT Authentication**: Secure token-based API authentication with automated expiration and route protection.

### 🏫 2. Classroom & Student Management
- Create classrooms with custom Name, Subject, and Grace Period (in minutes).
- Dynamic adjustment of Grace Period per class.
- Student un-enrollment / deletion with cascade cleanup.

### 📦 3. Bulk ZIP Student Enrollment
- Single-click ZIP file upload containing student photos.
- Automatic filename parsing: Supports formats such as `101_John_Doe.jpg` or `101.jpg`.
- Automatic face detection, 512-D embedding extraction, and reference image storage in `storage/enrollments/class_<id>/`.

### 📹 4. Asynchronous Video Processing & Progress Tracking
- Video processing runs in background threads (`threading.Thread`) so HTTP requests remain responsive.
- Real-time progress bar polling on the frontend (`/api/attendance/sessions/<id>/status`).
- Automatic state management (`pending` $\rightarrow$ `processing` $\rightarrow$ `done` / `error`).

### 📊 5. Comprehensive Attendance Analytics & Export
- Visual attendance breakdown cards: Present, Late-Absent, and Absent counts.
- Interactive data tables showing Roll Number, Name, Status, and First-Seen Timestamp.
- "Flagged for Review" section alerting faculty to low-confidence or borderline matches.
- One-click downloads for **Excel (.xlsx)** and **PDF (.pdf)** reports.

---

## 🗄️ Database Schema & Data Models

The SQLite database (`cctv_attendance.db`) consists of 5 core tables:

### 1. `users`
- `id` (INTEGER, Primary Key)
- `name` (VARCHAR(120), Required)
- `email` (VARCHAR(255), Unique, Indexed, Required)
- `password_hash` (VARCHAR(255), Required)
- `role` (VARCHAR(20), Default: `"faculty"`)
- `created_at` (DATETIME)

### 2. `classrooms`
- `id` (INTEGER, Primary Key)
- `name` (VARCHAR(120), Required)
- `subject` (VARCHAR(120), Required)
- `grace_period_minutes` (INTEGER, Default: `10`)
- `created_by` (INTEGER, Foreign Key -> `users.id`)
- `created_at` (DATETIME)

### 3. `students`
- `id` (INTEGER, Primary Key)
- `class_id` (INTEGER, Foreign Key -> `classrooms.id`)
- `roll_number` (VARCHAR(50), Required)
- `name` (VARCHAR(120), Required)
- `face_embedding` (JSON, Stores 512-D Float Array)
- `face_model` (VARCHAR(50), Stores model name)
- `reference_image_path` (VARCHAR(500))
- `enrolled_at` (DATETIME)
- *Constraint*: `UniqueConstraint("class_id", "roll_number")`

### 4. `attendance_sessions`
- `id` (INTEGER, Primary Key)
- `class_id` (INTEGER, Foreign Key -> `classrooms.id`)
- `uploaded_by` (INTEGER, Foreign Key -> `users.id`)
- `session_date` (DATE)
- `class_start_time` (DATETIME)
- `video_path` (VARCHAR(500))
- `processing_status` (VARCHAR(20), Default: `"pending"`)
- `progress_pct` (INTEGER, Default: `0`)
- `error_message` (TEXT)
- `created_at` (DATETIME)

### 5. `attendance_records`
- `id` (INTEGER, Primary Key)
- `session_id` (INTEGER, Foreign Key -> `attendance_sessions.id`)
- `student_id` (INTEGER, Foreign Key -> `students.id`)
- `status` (VARCHAR(20): `"present"`, `"late-absent"`, `"absent"`)
- `detected_at_seconds` (FLOAT)
- `flagged` (BOOLEAN, Default: `False`)
- `created_at` (DATETIME)

---

## 🌐 API Route Specifications

### **Auth Routes (`/api/auth`)**
- `POST /api/auth/login`: Authenticates user, returns JWT token & profile.
- `POST /api/auth/register`: Public registration for faculty members.
- `POST /api/auth/faculty`: (HOD only) Creates a new faculty account.
- `GET /api/auth/me`: Returns currently logged in user profile.

### **Classroom Routes (`/api/classes`)**
- `GET /api/classes`: Lists classrooms accessible to the active user.
- `POST /api/classes`: Creates a new classroom.
- `GET /api/classes/<id>`: Fetches specific classroom metadata.
- `PUT /api/classes/<id>`: Updates classroom settings (e.g. grace period).
- `DELETE /api/classes/<id>`: Deletes classroom and associated records.
- `GET /api/classes/<id>/students`: Lists all enrolled students.
- `POST /api/classes/<id>/enroll-zip`: Uploads ZIP file for student enrollment.
- `DELETE /api/classes/<id>/students/<student_id>`: Removes student enrollment.

### **Attendance Routes (`/api/attendance`)**
- `POST /api/attendance/upload-video`: Accepts video file upload, creates session, starts background processing.
- `GET /api/attendance/sessions`: Lists sessions for given classroom.
- `GET /api/attendance/sessions/<id>`: Fetches session summary, student records, and class info.
- `GET /api/attendance/sessions/<id>/status`: Returns real-time processing status & progress percentage.
- `POST /api/attendance/sessions/<id>/set-start-time`: Updates official class start time.

### **Report Routes (`/api/reports`)**
- `GET /api/reports/<session_id>/xlsx`: Generates and streams Excel `.xlsx` report download.
- `GET /api/reports/<session_id>/pdf`: Generates and streams PDF `.pdf` report download.

---

## 📁 Repository Directory Structure

```
CCTV-ATTENDENCE-MAJOR-PROJECT/
├── .env                         # Global environment variable configurations
├── .gitignore                   # Git ignore settings
├── create_test_kit.py           # Test kit utility (downloads test video & builds sample ZIP)
├── script3.py                   # Standalone CLI processing script using DeepFace
├── test_cctv.mp4                # Sample CCTV test video
├── Students.zip                 # Sample enrolled students dataset
│
├── backend/                     # Flask REST Backend
│   ├── run.py                   # Server starter script
│   ├── wsgi.py                  # WSGI entry point
│   ├── requirements.txt         # Python dependencies
│   ├── cctv_attendance.db       # SQLite database file
│   └── app/
│       ├── __init__.py          # Flask app factory, CORS, extension setup
│       ├── config.py            # Flask configuration mapping `.env`
│       ├── extensions.py        # SQLAlchemy, Migrate, JWT, Bcrypt initialization
│       ├── models/              # Database Models (User, Student, Classroom, Attendance)
│       ├── routes/              # API Blueprint Endpoints (auth, classes, attendance, reports)
│       ├── services/            # Deep Learning & Pipeline Core Services
│       │   ├── pipeline.py               # Orchestration pipeline (Steps 1–8)
│       │   ├── face_detection.py         # RetinaFace + ArcFace 5-point alignment
│       │   ├── recognition_adaptive.py   # AdaFace IR-101 CNN recognizer
│       │   ├── recognition_transformer.py# Swin Vision Transformer recognizer
│       │   ├── fusion.py                 # Feature fusion (Concatenation + MLP)
│       │   ├── matching.py               # Matrix-multiplied cosine similarity search
│       │   ├── first_appearance.py       # Earliest detection timestamp tracker
│       │   ├── attendance_decision.py    # Grace period decision rules
│       │   ├── enrollment_service.py     # ZIP extraction & student face embedding
│       │   ├── output_reports.py         # openpyxl & reportlab export generators
│       │   ├── attendance_service.py     # Threaded background runner
│       │   ├── video_ingest.py           # Video file validation
│       │   ├── frame_sampling.py         # OpenCV video frame generator
│       │   └── repositories.py           # DB repository abstractions
│       └── utils/               # Utility functions (security, files, time, seed)
│
├── frontend/                    # Vite + React 18 Frontend
│   ├── package.json             # JS Dependencies (React, Tailwind, Radix UI, Vite)
│   ├── vite.config.js           # Vite server & proxy configuration
│   ├── tailwind.config.js       # Custom Tailwind CSS theme settings
│   └── src/
│       ├── App.jsx              # Main React Application router & providers
│       ├── main.jsx             # DOM mounting entry point
│       ├── pages/               # Views (Login, Register, Dashboard, Class detail, Attendance report)
│       ├── components/          # Reusable UI components (Modal, StatusBadge, ProtectedRoute)
│       └── lib/                 # API services (`api.js`), Auth (`auth.js`), Utilities (`utils.js`)
│
└── storage/                     # Storage Directory
    ├── enrollments/             # Saved reference photos per class
    ├── reports/                 # Exported PDF and XLSX reports
    ├── tmp/                     # Extraction temporary files
    └── videos/                  # Uploaded CCTV video files
```

---

## 🚀 Step-by-Step Installation & Setup Guide

### **1. Prerequisites**
- Python 3.9+ installed on system.
- Node.js (v18+) & Yarn or NPM installed.
- (Optional) CUDA-enabled NVIDIA GPU for accelerated PyTorch / InsightFace execution.

---

### **2. Backend Setup**

1. Navigate to the `backend` directory:
   ```bash
   cd backend
   ```

2. Create and activate a Python virtual environment:
   ```bash
   python -m venv venv
   # Windows PowerShell:
   .\venv\Scripts\Activate.ps1
   # Linux/macOS:
   source venv/bin/activate
   ```

3. Install required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure environment variables in `.env` (placed in the root project folder):
   ```env
   FLASK_SECRET_KEY=your_super_secret_key
   JWT_SECRET_KEY=your_jwt_secret_key
   DATABASE_URL=sqlite:///cctv_attendance.db
   CORS_ORIGINS=http://localhost:5173
   FRAME_SAMPLE_EVERY=2.0
   MATCH_THRESHOLD=0.55
   DEFAULT_HOD_NAME=HOD Admin
   DEFAULT_HOD_EMAIL=hod@spit.ac.in
   DEFAULT_HOD_PASSWORD=adminpassword
   HOD_SEES_ALL=true
   ```

5. Run the Flask development server:
   ```bash
   python run.py
   ```
   The backend API will run at `http://localhost:5000`.

---

### **3. Frontend Setup**

1. Open a new terminal and navigate to the `frontend` directory:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   # or using yarn:
   yarn install
   ```

3. Start the Vite development server:
   ```bash
   npm run dev
   # or:
   yarn dev
   ```

4. Open `http://localhost:5173` in your browser.

---

### **4. Quick CLI Testing Script (Alternative Execution)**

If you prefer running a direct command-line test on a video without launching the web server:

1. Run the test kit creation script to generate sample data (`Students.zip` and `test_cctv.mp4`):
   ```bash
   python create_test_kit.py
   ```

2. Edit `script3.py` to specify your file paths:
   ```python
   ZIP_PATH = "Students.zip"
   VIDEO_PATH = "test_cctv.mp4"
   GRACE_PERIOD_MIN = 15
   ```

3. Execute the CLI script:
   ```bash
   python script3.py
   ```
   This will extract reference embeddings, sample frames from the CCTV video, perform face matching using DeepFace/FaceNet512, display a terminal summary, and export `attendance_report.csv`.

---

## 📈 Performance & Execution Benchmarks

- **Sampling Optimization**: Sampling 1 frame every 2.0 seconds reduces processed frame volume by up to 96% compared to raw 30 FPS video while preserving detection reliability.
- **Early Exit Mechanism**: If all $N$ enrolled students are matched early in the stream, the video decoder terminates immediately, saving processing time on long CCTV recordings.
- **Vectorized Search**: Cosine similarity calculation over thousands of face embeddings takes less than 1 millisecond per frame using NumPy matrix multiplication.
