import math
import os
from datetime import datetime
import numpy as np
import face_recognition
from flask import session, redirect, url_for

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import mysql.connector
from mysql.connector import Error
from flask import session
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a strong secret key

# Database configuration
db_config = {
    'host': 'sql12.freesqldatabase.com',
    'database': 'sql12752402',
    'user': 'sql12752402',
    'password': '3vfenwI4Y4'
}

# Configure upload folder
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database connection function
def get_db_connection():
    try:
        conn = mysql.connector.connect(**db_config)
        if conn.is_connected():
            return conn
    except Error as e:
        print(f"Database connection error: {e}")
        return None


@app.route('/home')
def home():
    if session.get('user_type') != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()
    total_stations = 0
    total_cameras = 0
    total_missing_persons = 0

    if conn:
        try:
            cursor = conn.cursor()

            # Query to get total stations
            cursor.execute("SELECT COUNT(*) FROM stations")
            total_stations = cursor.fetchone()[0]

            # Query to get total cameras
            cursor.execute("SELECT COUNT(*) FROM cameras")
            total_cameras = cursor.fetchone()[0]

            # Query to get total missing persons
            cursor.execute("SELECT COUNT(*) FROM missing_person")
            total_missing_persons = cursor.fetchone()[0]

        except Exception as e:
            flash(f"Database query error: {e}", 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template(
        'home.html',
        total_stations=total_stations,
        total_cameras=total_cameras,
        total_missing_persons=total_missing_persons
    )


@app.route('/dashboard')
def dashboard():
    # Check if the user is logged in and is a 'station' user
    if session.get('user_type') != 'station':
        return redirect(url_for('login'))

    station_id = session.get('user_id')  # Assume user_id corresponds to station_id
    conn = get_db_connection()

    total_stations = 0
    total_missing_cases = 0

    if conn:
        cursor = conn.cursor()

        # Fetch missing cases count only for the specific station
        cursor.execute("SELECT COUNT(*) FROM missing_person WHERE station_id = %s", (station_id,))
        total_missing_cases = cursor.fetchone()[0]

        cursor.close()
        conn.close()

    # Pass only the filtered missing cases count to the template
    return render_template('dashboard.html', total_missing_cases=total_missing_cases)

# Haversine formula to calculate distance between two coordinates
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in kilometers
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(
        d_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@app.route('/notify_station', methods=['POST'])
def notify_station():
    # Get JSON data from the request
    json_data = request.get_json()

    # Extract data from the JSON
    camera_id = json_data.get("camera_id")
    missing_person_id = json_data.get("missing_person_id")
    identify_date = datetime.now().strftime('%Y-%m-%d')

    # Validate the required fields
    if not camera_id or not missing_person_id or not identify_date:
        return jsonify({"error": "camera_id, missing_person_id, and identify_date are required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection error"}), 500

    try:
        cursor = conn.cursor(dictionary=True)

        # Fetch the missing person details with the provided missing_person_id
        cursor.execute("""
            SELECT mp.id AS missing_person_id, mp.name AS missing_person_name, 
                   s.id AS station_id, s.station_name, s.station_email
            FROM missing_person mp
            JOIN stations s ON mp.station_id = s.id
            WHERE mp.id = %s
        """, (missing_person_id,))
        missing_person = cursor.fetchone()

        # Debugging: Check if the missing person is found
        if not missing_person:
            print(f"No missing person found with ID: {missing_person_id}")
            return jsonify({"error": "Missing person not found"}), 404

        # Construct the notification message
        notification_message = (
            f"Notification for Station: {missing_person['station_name']} (ID: {missing_person['station_id']})\n"
            f"Camera ID: {camera_id} detected a missing person (ID: {missing_person['missing_person_id']} - "
            f"{missing_person['missing_person_name']})."
        )

        # Insert the notification into the `notifications` table
        cursor.execute("""
            INSERT INTO notifications (camera_id, station_id, missing_person_id)
            VALUES (%s, %s, %s)
        """, (camera_id, missing_person["station_id"], missing_person["missing_person_id"]))
        conn.commit()

        # Insert the notification into the `history` table
        cursor.execute("""
            INSERT INTO history (missing_person_id, camera_id, identify_date)
            VALUES (%s, %s, %s)
        """, (missing_person["missing_person_id"], camera_id, identify_date))
        conn.commit()

        # Construct the response
        response = {
            "camera_id": camera_id,
            "missing_person_id": missing_person["missing_person_id"],
            "missing_person_name": missing_person["missing_person_name"],
            "notification": notification_message,
            "station_id": missing_person["station_id"],
            "station_name": missing_person["station_name"],
            "station_email": missing_person["station_email"]
        }

        return jsonify(response), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": f"An error occurred: {e}"}), 500
    finally:
        cursor.close()
        conn.close()



@app.route('/get_notification_messages', methods=['GET'])
def get_notification_messages():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection error"}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        station_id = request.args.get('station_id')

        # Check if station_id is provided
        if not station_id:
            return jsonify({"error": "station_id is required"}), 400

        # Query to fetch notifications for the specified station_id and where status is 'unseen'
        query = """
            SELECT 
                mp.name AS missing_person_name, 
                c.address AS camera_address, 
                s.station_name
            FROM 
                notifications n
            LEFT JOIN cameras c ON n.camera_id = c.id
            LEFT JOIN stations s ON n.station_id = s.id
            LEFT JOIN missing_person mp ON n.missing_person_id = mp.id
            WHERE n.station_id = %s AND n.status = 'unseen'
        """
        cursor.execute(query, (station_id,))
        notifications = cursor.fetchall()

        # If no notifications, return 404 with a message and count as 0
        if not notifications:
            return jsonify({"count": 0, "messages": []}), 200

        # Extract and return the messages
        messages = []
        for notification in notifications:
            messages.append({
                "message": (
                    f"Alert! Missing person '{notification['missing_person_name']}' was detected by "
                    f"the camera located at '{notification['camera_address']}' and is associated with "
                    f"station '{notification['station_name']}'."
                )
            })

        return jsonify({"count": len(messages), "messages": messages}), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": f"An error occurred: {e}"}), 500
    finally:
        cursor.close()
        conn.close()


from flask import session, render_template, jsonify
import mysql.connector

@app.route('/notification')
def notification():
    # Get the station_id from the session
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "User not logged in"}), 401

    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        # Query to fetch notifications based on station_id from the session
        query = """
        SELECT 
            n.id AS notification_id,
            n.camera_id,
            n.station_id,
            n.missing_person_id,
            n.status AS notification_status,
            LEFT(c.address, 256) AS camera_address,
            LEFT(mp.name, 256) AS missing_person_name,
            LEFT(mp.birthdate, 256) AS missing_person_birthdate,
            LEFT(mp.address, 256) AS missing_person_address,
            LEFT(mp.missingdate, 256) AS missing_date,
            LEFT(mp.complaintdate, 256) AS complaint_date,
            mp.criminal AS is_criminal,
            LEFT(mp.aadharCardNo, 256) AS aadhar_card_no,
            LEFT(mp.photo, 256) AS missing_person_photo
        FROM 
            notifications n
        LEFT JOIN 
            cameras c 
        ON 
            n.camera_id = c.id
        LEFT JOIN 
            missing_person mp
        ON 
            n.missing_person_id = mp.id
        WHERE 
            n.station_id = %s  -- Filter by the station_id from the session
        """
        cursor.execute(query, (user_id,))
        notifications = cursor.fetchall()

    except mysql.connector.Error as err:
        print(f"Error: {err}")
        notifications = []
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    # Render the notification page with the fetched data
    return render_template('notification.html', notifications=notifications)


@app.route('/update_notification_status/<int:notification_id>/<string:status>', methods=['GET'])
def update_notification_status(notification_id, status):
    try:
        # Connect to the database
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()

        # Update the notification status in the database
        query = "UPDATE notifications SET status = %s WHERE id = %s"
        cursor.execute(query, (status, notification_id))
        connection.commit()

        # If the update is successful, return a success response
        return jsonify({"success": True})

    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return jsonify({"success": False, "error": "Failed to update notification status"})

    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@app.route('/case', methods=['GET', 'POST'])
def case():
    # Check if the user is logged in and is a 'station' user
    if session.get('user_type') != 'station':
        return redirect(url_for('login'))

    # Get the station_id from session
    station_id = session.get('user_id')  # Assuming 'user_id' corresponds to the station's ID

    if request.method == 'POST':
        # Get form data, excluding station_id (since it comes from the session)
        name = request.form['name']
        birthdate = request.form['birthdate']
        address = request.form['address']
        missingdate = request.form['missingdate']
        complaintdate = request.form['complaintdate']
        criminal = request.form['criminal']
        aadharCardNo = request.form['aadharCardNo']
        photo = request.files['photo']

        # Save photo
        photo_path = f"static/uploads/{photo.filename}"
        photo.save(photo_path)

        # Insert data into missing_person table with station_id from session
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                insert_query = """
                INSERT INTO missing_person (station_id, name, birthdate, address, missingdate, complaintdate, criminal, aadharCardNo, photo)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(insert_query, (
                station_id, name, birthdate, address, missingdate, complaintdate, criminal, aadharCardNo, photo_path))
                conn.commit()
                flash('Missing person record added successfully!', 'success')
            except Exception as e:
                conn.rollback()
                flash(f'Error inserting data: {e}', 'danger')
            finally:
                cursor.close()
                conn.close()
        else:
            flash('Database connection error.', 'danger')

        return redirect(url_for('case'))

    # For GET requests, fetch missing person records only for this station
    missing_persons = []
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM missing_person WHERE station_id = %s", (station_id,))
            missing_persons = cursor.fetchall()
        except Exception as e:
            flash(f'Error fetching data: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('case.html', missing_persons=missing_persons)

@app.route('/add_cameras', methods=['GET', 'POST'])
def add_cameras():
    if session.get('user_type') != 'admin':
        return redirect(url_for('login'))
    if request.method == 'POST':
        # Retrieve form data
        address = request.form['address']
        longitude = request.form['longitude']
        latitude = request.form['latitude']
        status = request.form['status']

        # Insert into the database
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                insert_query = """
                INSERT INTO cameras (address, longitude, latitude, status)
                VALUES (%s, %s, %s, %s)
                """
                cursor.execute(insert_query, (address, longitude, latitude, status))
                conn.commit()
                flash('Camera added successfully!', 'success')
            except Error as e:
                conn.rollback()
                flash(f"Error adding camera: {e}", 'danger')
            finally:
                cursor.close()
                conn.close()
        else:
            flash('Database connection error.', 'danger')

        return redirect(url_for('add_cameras'))

    # Fetch all cameras for display
    cameras = []
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM cameras")
            cameras = cursor.fetchall()
        except Error as e:
            flash(f"Error fetching cameras: {e}", 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('cameras.html', cameras=cameras)


# Update camera API
from flask import flash, redirect, url_for

@app.route('/update_camera/<int:camera_id>', methods=['GET', 'POST'])
def update_camera(camera_id):
    try:
        conn = get_db_connection()
        if conn is None:
            flash("Database connection failed", "danger")
            return redirect(url_for('index'))

        cursor = conn.cursor()

        # Handle GET request to fetch camera data by ID
        if request.method == 'GET':
            cursor.execute("SELECT * FROM cameras WHERE id = %s", (camera_id,))
            columns = [col[0] for col in cursor.description]  # Get column names
            camera = dict(zip(columns, cursor.fetchone()))  # Convert to dictionary

            if not camera:
                flash("Camera not found", "danger")
                return redirect(url_for('index'))

            # Return data to populate form
            return render_template('update_camera.html', camera=camera)

        # Handle POST request to update camera data
        if request.method == 'POST':
            data = request.form  # Getting form data
            address = data.get('address')
            longitude = data.get('longitude')
            latitude = data.get('latitude')
            status = data.get('status')

            # Prepare the update query
            update_query = """
            UPDATE cameras
            SET address = %s, longitude = %s, latitude = %s, status = %s
            WHERE id = %s
            """
            cursor.execute(update_query, (address, longitude, latitude, status, camera_id))
            conn.commit()

            flash("Camera updated successfully", "success")
            return redirect(url_for('add_cameras', camera_id=camera_id))

    except Exception as e:
        print(f"Error updating camera: {e}")
        flash("Failed to update camera", "danger")
        return redirect(url_for('index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()




# Delete camera API
@app.route('/delete_camera/<int:camera_id>', methods=['DELETE'])
def delete_camera(camera_id):
    try:
        conn = get_db_connection()
        if conn is None:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor()
        delete_query = "DELETE FROM cameras WHERE id = %s"
        cursor.execute(delete_query, (camera_id,))
        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({"error": "Camera not found"}), 404

        return jsonify({"success": "Camera deleted successfully"}), 200

    except Error as e:
        print(f"Error deleting camera: {e}")
        return jsonify({"error": "Failed to delete camera"}), 500
    finally:
        if conn:
            conn.close()






@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Establish database connection
        conn = get_db_connection()

        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()

            if user and user['password'] == password:
                # Set user_type in the session
                session['user_id'] = user['id']
                session['user_email'] = user['email']
                session['user_type'] = user['user_type']

                flash('Login successful!', 'success')

                # Redirect based on user type
                if user['user_type'] == 'admin':
                    return redirect(url_for('home'))
                elif user['user_type'] == 'station':
                    return redirect(url_for('dashboard'))
            else:
                flash('Login failed. Check your credentials.', 'danger')

            cursor.close()
            conn.close()
        else:
            flash('Database connection error.', 'danger')

    return render_template('login.html')


@app.route('/stations', methods=['GET', 'POST'])
def stations():
    # Check if the user is logged in and is an 'admin' user
    if session.get('user_type') != 'admin':
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Get form data from the submitted form
        station_name = request.form['station_name']
        station_email = request.form['station_email']
        password = request.form['password']
        station_mobile_no = request.form['station_mobile_no']
        longitude = request.form['longitude']
        latitude = request.form['latitude']
        state = request.form['state']
        district = request.form['district']
        division = request.form['division']
        city = request.form['city']
        date = request.form['date']

        # Connect to the database
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()

                # Insert station email and password into the users table with user_type='station'
                insert_user_query = """
                INSERT INTO users (email, password, user_type)
                VALUES (%s, %s, %s)
                """
                cursor.execute(insert_user_query, (station_email, password, 'station'))

                # Get the last inserted user ID
                user_id = cursor.lastrowid

                # Insert station data into the Stations table, using the user ID as station_id
                insert_station_query = """
                INSERT INTO stations (station_name, station_email, password, station_mobile_no, longitude, latitude, 
                                      state, district, division, city, date, id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(insert_station_query, (
                    station_name, station_email, password, station_mobile_no, longitude, latitude, state, district,
                    division, city, date, user_id
                ))

                # Commit the transaction to save the changes
                conn.commit()
                flash('Station and user added successfully!', 'success')

            except Exception as e:
                conn.rollback()  # Rollback in case of an error
                flash(f'Error inserting data: {e}', 'danger')

            finally:
                cursor.close()
                conn.close()  # Close the cursor and the connection after use
        else:
            flash('Database connection error.', 'danger')

        return redirect(url_for('stations'))

    # For GET requests, fetch all stations from the database
    stations = []
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM stations")
            # Fetch all stations and map them to a list of dictionaries
            stations = [
                {
                    'id': row[0],
                    'station_name': row[1],
                    'station_email': row[2],
                    'station_mobile_no': row[4],
                    'longitude': row[5],
                    'latitude': row[6],
                    'state': row[7],
                    'district': row[8],
                    'division': row[9],
                    'city': row[10],
                    'date': row[11]
                }
                for row in cursor.fetchall()
            ]
        except Exception as e:
            flash(f'Error fetching stations: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()

    # Render the page with the list of stations
    return render_template('stations.html', stations=stations)


# Update station API
@app.route('/update_station/<int:station_id>', methods=['GET', 'POST'])
def update_station(station_id):
    try:
        conn = get_db_connection()
        if conn is None:
            flash("Database connection failed", "danger")  # Error message with 'danger' category
            return render_template('update_station.html')

        cursor = conn.cursor()

        # Fetch station data based on station_id
        cursor.execute("SELECT * FROM stations WHERE id = %s", (station_id,))
        station = cursor.fetchone()

        if not station:
            flash("Station not found", "danger")  # Error message with 'danger' category
            return render_template('update_station.html')

        # If the request is GET, render the update form with the station data
        if request.method == 'GET':
            return render_template('update_station.html', station=station)

        # Handle POST request for updating station data
        if request.method == 'POST':
            data = request.form.to_dict()
            station_name = data.get('station_name')
            station_email = data.get('station_email')
            password = data.get('password')
            station_mobile_no = data.get('station_mobile_no')
            longitude = data.get('longitude')
            latitude = data.get('latitude')
            state = data.get('state')
            district = data.get('district')
            division = data.get('division')
            city = data.get('city')

            update_query = """
            UPDATE stations
            SET station_name = %s, station_email = %s, password = %s,
                station_mobile_no = %s, longitude = %s, latitude = %s,
                state = %s, district = %s, division = %s, city = %s
            WHERE id = %s
            """
            cursor.execute(update_query, (
                station_name, station_email, password, station_mobile_no,
                longitude, latitude, state, district, division, city, station_id
            ))
            conn.commit()
            cursor.close()
            conn.close()

            flash("Station updated successfully", "success")  # Success message with 'success' category
            return redirect(url_for('stations')) # Re-render form with updated data
    except Exception as e:
        print(f"Error: {e}")
        flash("An error occurred while updating the station", "danger")  # Error message
        return render_template('update_station.html')



@app.route('/api/stations/<int:station_id>', methods=['DELETE'])
def delete_station(station_id):
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Failed to connect to the database"}), 500

        cursor = conn.cursor()

        # Fetch station email before deleting the station
        cursor.execute("SELECT station_email FROM stations WHERE id = %s", (station_id,))
        station = cursor.fetchone()

        if not station:
            return jsonify({"error": "Station not found"}), 404

        station_email = station[0]

        # Delete the station record
        delete_station_query = "DELETE FROM stations WHERE id = %s"
        cursor.execute(delete_station_query, (station_id,))
        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({"error": "Failed to delete station"}), 500

        # Check and delete user with the same email in the users table
        cursor.execute("DELETE FROM users WHERE email = %s", (station_email,))
        conn.commit()

        return jsonify({"message": "Station and associated user (if any) deleted successfully"}), 200
    except Exception as e:
        print(f"Error deleting station: {e}")
        return jsonify({"error": f"Error deleting station: {str(e)}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()




# Update missing person API
@app.route('/update_missing_person/<int:person_id>', methods=['GET', 'POST'])
def update_missing_person(person_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get the existing missing person details from the database
    cursor.execute("SELECT * FROM missing_person WHERE id = %s", (person_id,))
    person = cursor.fetchone()

    if not person:
        return jsonify({"error": "Person not found"}), 404

    if request.method == 'POST':
        # Process form submission and update the database
        data = request.form  # Form data from POST
        photo = request.files.get('photo')  # Handle file upload

        fields_to_update = [
            'station_id', 'name', 'birthdate', 'address',
            'missingdate', 'complaintdate', 'criminal',
            'aadharCardNo', 'laststatus', 'status'
        ]

        update_fields = []
        update_values = []

        # Process text fields
        for field in fields_to_update:
            if field in data:
                update_fields.append(f"{field} = %s")
                update_values.append(data[field])

        # Handle photo update
        if photo:
            filename = secure_filename(photo.filename)
            new_photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            photo.save(new_photo_path)
            update_fields.append("photo = %s")
            update_values.append(new_photo_path)

        if update_fields:
            # Construct the UPDATE query
            update_query = f"UPDATE missing_person SET {', '.join(update_fields)} WHERE id = %s"
            update_values.append(person_id)
            cursor.execute(update_query, tuple(update_values))
            conn.commit()

            # Flash a success message
            flash("Missing person record updated successfully", "success")
        else:
            # Flash an error message if no valid fields to update
            flash("No valid fields to update", "error")

        # Redirect to the 'case' page after the update
        return redirect(url_for('case'))

    # Render the form with the current missing person details
    return render_template('update_missing_person.html', person=person)

# Delete missing person API
@app.route('/delete_missing_person/<int:person_id>', methods=['DELETE'])
def delete_missing_person(person_id):
    try:
        conn = get_db_connection()
        if conn is None:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor()
        # Fetch the current photo path
        cursor.execute("SELECT photo FROM missing_person WHERE id = %s", (person_id,))
        result = cursor.fetchone()
        if result and result[0]:
            old_photo_path = result[0]
            # Delete the photo file
            if os.path.exists(old_photo_path):
                os.remove(old_photo_path)

        # Delete the database record
        delete_query = "DELETE FROM missing_person WHERE id = %s"
        cursor.execute(delete_query, (person_id,))
        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({"error": "Missing person record not found"}), 404

        return jsonify({"success": "Missing person record deleted successfully"}), 200

    except Error as e:
        print(f"Error deleting missing person record: {e}")
        return jsonify({"error": "Failed to delete missing person record"}), 500
    finally:
        if conn:
            conn.close()


@app.route('/logout')
def logout():
    # Clear all session data
    session.clear()
    # Redirect the user to the login page (default '/')
    return redirect(url_for('login'))

# Load missing persons data from the database
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
        print(f"Error fetching data: {e}")
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

# Flask route for finding a missing person
@app.route("/find-missing-person", methods=["GET", "POST"])
def find_missing_person():
    if request.method == "GET":
        # Render the page with the form to upload the photo
        return render_template("find-missing-person.html")

    if request.method == "POST":
        if "photo" not in request.files:
            return jsonify({"error": "No photo uploaded"}), 400

        # Save the uploaded photo temporarily
        uploaded_file = request.files["photo"]
        temp_photo_path = "temp_uploaded_photo.jpg"
        uploaded_file.save(temp_photo_path)

        try:
            # Load and encode the uploaded image
            uploaded_image = face_recognition.load_image_file(temp_photo_path)
            uploaded_encodings = face_recognition.face_encodings(uploaded_image)

            if not uploaded_encodings:
                return jsonify({"error": "No face found in the uploaded photo"}), 400

            uploaded_encoding = uploaded_encodings[0]

            # Ensure reference_encodings is not empty
            if not reference_encodings:
                return jsonify({"error": "No reference data available for comparison"}), 500

            # Compare with reference encodings
            face_distances = face_recognition.face_distance(reference_encodings, uploaded_encoding)

            if not face_distances.size:  # Check if face_distances is empty
                return jsonify({"match": False, "message": "No matches found in the database"}), 200

            best_match_index = np.argmin(face_distances)

            # Check if the best match is within a reasonable distance
            if face_distances[best_match_index] < 0.6:  # Threshold for match
                matched_person = missing_persons_data[best_match_index]
                confidence = 1.0 - face_distances[best_match_index]
                return jsonify({
                    "match": True,
                    "details": {
                        "name": matched_person["name"],
                        "birthdate": matched_person["birthdate"],
                        "address": matched_person["address"],
                        "missingdate": matched_person["missingdate"],
                        "complaintdate": matched_person["complaintdate"],
                        "criminal": matched_person["criminal"],
                        "aadharCardNo": matched_person["aadharCardNo"],
                        "laststatus": matched_person["laststatus"],
                        "status": matched_person["status"],
                        "photo": matched_person["photo"],
                        "confidence": round(confidence, 2)
                    }
                })
            else:
                return jsonify({"match": False, "message": "No match found"}), 200

        except Exception as e:
            return jsonify({"error": f"An error occurred: {str(e)}"}), 500

        finally:
            # Remove the temporary uploaded photo
            if os.path.exists(temp_photo_path):
                os.remove(temp_photo_path)


if __name__ == '__main__':
    app.run(debug=True,host='0.0.0.0')
