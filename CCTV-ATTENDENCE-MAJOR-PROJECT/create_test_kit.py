import cv2
import os
import zipfile
import urllib.request

video_path = "test_cctv.mp4"
if not os.path.exists(video_path):
    print("Downloading video...")
    url='https://raw.githubusercontent.com/intel-iot-devkit/sample-videos/master/head-pose-face-detection-female-and-male.mp4'
    urllib.request.urlretrieve(url, video_path)

students_dir = "Students"
os.makedirs(students_dir, exist_ok=True)

# Load OpenCV face detector
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

cap = cv2.VideoCapture(video_path)
fps = cap.get(cv2.CAP_PROP_FPS)

person_count = 1
frame_count = 0
saved_hashes = []

while cap.isOpened() and person_count <= 2:
    ret, frame = cap.read()
    if not ret:
        break
    
    # Check every 20th frame to skip similar frames
    if frame_count % 20 == 0:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        
        for (x, y, w, h) in faces:
            if w > 50 and h > 50:
                # Crop with a little margin
                margin = int(w * 0.2)
                y1 = max(0, y - margin)
                y2 = min(frame.shape[0], y + h + margin)
                x1 = max(0, x - margin)
                x2 = min(frame.shape[1], x + w + margin)
                
                face_img = frame[y1:y2, x1:x2]
                
                filename = os.path.join(students_dir, f"10{person_count}_TestUser{person_count}.jpg")
                cv2.imwrite(filename, face_img)
                print(f"Saved {filename}")
                person_count += 1
                if person_count > 2:
                    break
            
    frame_count += 1

cap.release()

zip_path = "Students.zip"
with zipfile.ZipFile(zip_path, 'w') as zipf:
    for root, _, files in os.walk(students_dir):
        for file in files:
            zipf.write(os.path.join(root, file), file)

print(f"Test kit generated! ZIP created at {zip_path} and Video is at {video_path}")
