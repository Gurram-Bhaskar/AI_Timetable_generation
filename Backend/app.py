from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector
import time

# --- IMPORT THE REAL SOLVER ---
try:
    from solver import generate_schedule # This is now the new "smart" solver
    print("Successfully imported REAL solver.")
except ImportError:
    print("ERROR: Could not import solver.py. Make sure it's in the same folder.")
    def generate_schedule(data, temporary_constraints=None, previous_schedule=None):
        print("Using DUMMY solver. 'solver.py' not found.")
        return None

# --- DATABASE CONFIGURATION ---
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'bhaskar#1234',  # <-- This is correct
    'database': 'timetable'
}

def get_db_connection():
    try:
        conn = mysql.connector.connect(**db_config)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

# Initialize the app
app = Flask(__name__)
CORS(app)

# ==========================================================
#  UPDATED: REAL DATABASE QUERY FUNCTION
# ==========================================================
# This function is now smarter and handles the new timeslots
def get_all_solver_data():
    conn = get_db_connection()
    if not conn:
        raise Exception("Cannot connect to database")
    
    cursor = conn.cursor(dictionary=True)
    print("Querying database for all REAL solver data...")
    
    # 1. Get Courses
    cursor.execute("SELECT id, code, title as name, type, enrollment FROM course")
    courses = cursor.fetchall()
    
    # 2. Get Rooms
    cursor.execute("SELECT id, name, capacity, type FROM room")
    rooms = cursor.fetchall()
    
    # 3. Get Faculty
    cursor.execute("SELECT id, name FROM faculty")
    faculty = cursor.fetchall()
    
    # 4. Get Student Elections
    cursor.execute("SELECT student_id, course_id FROM student_course")
    student_elections = cursor.fetchall()
    
    # 5. Get all Timeslots (Now 35)
    #    We MUST order by day, then start_time to build the map correctly
    cursor.execute("SELECT id, day_of_week, start_time FROM timeslot ORDER BY field(day_of_week, 'Mon', 'Tue', 'Wed', 'Thu', 'Fri'), start_time")
    all_timeslots_db = cursor.fetchall()
    
    # 6. Get Faculty Availability
    cursor.execute("SELECT entity_id as faculty_id, timeslot_id FROM constraint_log WHERE constraint_type = 'FACULTY_AVAIL' AND entity_type = 'FACULTY'")
    availability_rows = cursor.fetchall()
    
    # 7. Get Faculty Preferences
    cursor.execute("SELECT faculty_id, course_id FROM faculty_preference")
    preference_rows = cursor.fetchall()

    # --- Re-format this data to match the Data Contract ---
    
    faculty_availability = {} 
    for row in availability_rows:
        f_id = row['faculty_id']
        t_id = row['timeslot_id']
        if f_id not in faculty_availability:
            faculty_availability[f_id] = []
        faculty_availability[f_id].append(t_id)

    faculty_preferences = {} 
    for row in preference_rows:
        c_id = row['course_id']
        f_id = row['faculty_id']
        if c_id not in faculty_preferences:
            faculty_preferences[c_id] = []
        faculty_preferences[c_id].append(f_id)
        
    # ==========================================================
    #  THIS IS THE CORRECTED LOGIC BLOCK
    # ==========================================================
    # --- Map database timeslot IDs (1-35) to solver tuples ( (0,0), (0,1)... ) ---
    timeslot_id_map = {} # {1: (0,0), 2: (0,1), ...}
    day_map = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4}
    
    # This logic is now robust and reads the DB order
    # A separate counter for each day
    slot_indices = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0} 
    
    for ts in all_timeslots_db:
        day_name = ts['day_of_week']
        day_num = day_map.get(day_name)
        
        if day_num is None: # Skip Sat/Sun
            continue
            
        # Get the current slot index for this day
        current_slot_index = slot_indices[day_num]
        
        # Map the ID to the (day, slot) tuple
        timeslot_id_map[ts['id']] = (day_num, current_slot_index)
        
        # Increment the slot index FOR THAT DAY ONLY
        slot_indices[day_num] += 1
            
    ALL_TIMESLOTS_AS_TUPLES = list(timeslot_id_map.values())
    # ==========================================================
    #  END OF CORRECTED LOGIC
    # ==========================================================
    
    for f in faculty:
        f['availability'] = [timeslot_id_map[t_id] for t_id in faculty_availability.get(f['id'], []) if t_id in timeslot_id_map]

    for c in courses:
        c['preferred_faculty'] = faculty_preferences.get(c['id'], [])

    conn.close()
    
    print(f"Loaded {len(courses)} courses, {len(ALL_TIMESLOTS_AS_TUPLES)} timeslots, {len(student_elections)} enrollments.")
    
    return {
        "COURSES": courses,
        "FACULTY": faculty,
        "ROOMS": rooms,
        "STUDENT_ELECTIONS": student_elections,
        "ALL_TIMESLOTS": ALL_TIMESLOTS_AS_TUPLES,
        "TIMESLOT_ID_MAP": timeslot_id_map 
    }

# --- API ENDPOINTS ---

@app.route('/api/health', methods=['GET'])
def health_check():
    conn = get_db_connection()
    if conn:
        conn.close()
        return jsonify({"status": "ok", "database": "connected"})
    else:
        return jsonify({"status": "error", "database": "disconnected"}), 500

# (CRUD Endpoints: /api/faculty, /api/courses, /api/rooms are unchanged)
@app.route('/api/faculty', methods=['GET'])
def get_faculty():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, department FROM faculty")
    result = cursor.fetchall()
    conn.close()
    return jsonify(result)
@app.route('/api/courses', methods=['GET'])
def get_courses():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, code, title as name, type, enrollment FROM course")
    result = cursor.fetchall()
    conn.close()
    return jsonify(result)
@app.route('/api/rooms', methods=['GET'])
def get_rooms():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, capacity, type FROM room")
    result = cursor.fetchall()
    conn.close()
    return jsonify(result)

# --- REAL SOLVER ENDPOINT ---
@app.route('/api/run-solver', methods=['POST'])
def run_real_solver():
    print("REAL solver triggered!")
    try:
        solver_data_package = get_all_solver_data()
        solver_data = {k: v for k, v in solver_data_package.items() if k != 'TIMESLOT_ID_MAP'}

        # Call solver with no previous schedule
        final_schedule = generate_schedule(solver_data, temporary_constraints=None, previous_schedule=None)
        
        if final_schedule:
            print("Real solver SUCCESS. Saving to timetable...")
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM timetable") # Clear old timetable
            
            sql = "INSERT INTO timetable (course_id, faculty_id, room_id, timeslot_id) VALUES (%s, %s, %s, %s)"
            reverse_timeslot_map = {v: k for k, v in solver_data_package['TIMESLOT_ID_MAP'].items()}
            
            insert_data = []
            for item in final_schedule:
                timeslot_tuple = (item['day'], item['slot'])
                timeslot_id = reverse_timeslot_map.get(timeslot_tuple)
                if timeslot_id:
                    insert_data.append((
                        item['course']['id'], item['faculty']['id'],
                        item['room']['id'], timeslot_id
                    ))
            
            cursor.executemany(sql, insert_data)
            conn.commit()
            conn.close()
            
            return jsonify(final_schedule)
        else:
            print("Real solver FAILED. No solution found.")
            return jsonify({"error": "No solution could be found."}), 400
    except Exception as e:
        print(f"An error occurred while running the solver: {e}")
        return jsonify({"error": f"An internal error occurred: {e}"}), 500

# ==========================================================
#  UPGRADED "WINNING FEATURE" ENDPOINT
# ==========================================================
@app.route('/api/reschedule', methods=['POST'])
def run_rescheduler():
    print("SMART RESCHEDULER triggered!")
    
    # 1. Get the data from the frontend
    request_data = request.json
    new_constraint = request_data.get("constraint")
    previous_schedule = request_data.get("previous_schedule") # <-- NEW
    
    if not new_constraint or not previous_schedule:
        return jsonify({"error": "Missing constraint or previous schedule data."}), 400
        
    print(f"Received new constraint: {new_constraint}")

    try:
        # 2. Get all the main solver data from DB
        solver_data_package = get_all_solver_data()
        solver_data = {k: v for k, v in solver_data_package.items() if k != 'TIMESLOT_ID_MAP'}

        # 3. Call the "smart" solver, passing BOTH the constraint AND the previous schedule
        final_schedule = generate_schedule(
            solver_data, 
            temporary_constraints=[new_constraint],
            previous_schedule=previous_schedule # <-- NEW
        )
        
        if final_schedule:
            print("Reschedule SUCCESS. Returning new schedule.")
            # We would also save this new schedule to the DB...
            return jsonify(final_schedule)
        else:
            print("Reschedule FAILED. No solution found with new constraint.")
            return jsonify({"error": "No solution could be found with the new constraint."}), 400
            
    except Exception as e:
        print(f"An error occurred while running the rescheduler: {e}")
        return jsonify({"error": f"An internal error occurred: {e}"}), 500

# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=True, port=5000)