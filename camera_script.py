import cv2
import face_recognition
import numpy as np
import requests
from app import get_db_connection

# Connect to the database and load missing persons data
missing_persons_data = []
reference_image_paths = []

conn = get_db_connection()
if conn:
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM missing_person")
        missing_persons_data = cursor.fetchall()

        # Extract photo paths from missing persons data
        reference_image_paths = [person['photo'] for person in missing_persons_data if 'photo' in person]

    except Exception as e:
        print(f'Error fetching data: {e}')
    finally:
        cursor.close()
        conn.close()

# Create a mapping from image paths to person details (name and ID)
reference_encodings = []
reference_names = []  # Store tuples of (name, id)

for person in missing_persons_data:
    path = person.get('photo')
    if path:
        try:
            image = face_recognition.load_image_file(path)
            encodings = face_recognition.face_encodings(image)
            if encodings:
                reference_encodings.append(encodings[0])
                reference_names.append((person['name'], person['id']))  # Store both name and ID
            else:
                print(f"Warning: No face found in {path}")
        except Exception as e:
            print(f"Error loading image at {path}: {e}")

# Start video capture
video_capture = cv2.VideoCapture(0)
video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)


def notify_station(camera_id, person_id):
    url = "http://192.168.31.216:5000/notify_station"
    payload = {"camera_id": camera_id, "missing_person_id": person_id}

    try:
        print(f"Sending POST request to {url} with payload: {payload}")
        response = requests.post(url, json=payload, timeout=5)  # Add timeout for stability
        print(f"Response Status: {response.status_code}, Response Body: {response.text}")

        if response.status_code == 200:
            print(f"Notification sent successfully for person ID {person_id}")
        else:
            print(f"Failed to send notification: Status Code {response.status_code}, Response: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending notification: {e}")

# Main loop for face recognition
try:
    while True:
        ret, frame = video_capture.read()
        if not ret:
            print("Error: Unable to read from the video capture.")
            break

        # Convert the frame to RGB (face_recognition uses RGB format)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Detect faces and encode them in the current frame
        face_locations = face_recognition.face_locations(rgb_frame)
        if face_locations:
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

            # Loop through each face found in the frame
            for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
                # Check if the face matches any reference encodings
                face_distances = face_recognition.face_distance(reference_encodings, face_encoding)
                best_match_index = np.argmin(face_distances)
                name = "No Match"
                confidence = 1.0 - face_distances[best_match_index]  # Higher confidence indicates better match
                person_id = None

                # Display match only if confidence > 0.6 (accuracy > 60%)
                if confidence > 0.6:
                    name, person_id = reference_names[best_match_index]

                    notify_station(camera_id=6, person_id=person_id)

                    # Draw a box around the face
                    color = (0, 255, 0)  # Green for matches
                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)

                    # Display name, ID, and confidence on the frame
                    label = f"{name} (ID: {person_id}, {confidence:.2f})"
                    cv2.putText(frame, label, (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

                else:
                    # Draw a box in red for no matches
                    color = (0, 0, 255)
                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                    cv2.putText(frame, "No Match", (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # Display the resulting frame
        cv2.imshow("Face Recognition", frame)

        # Break the loop on 'q' key
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

finally:
    # Release the capture and close OpenCV windows
    video_capture.release()
    cv2.destroyAllWindows()



