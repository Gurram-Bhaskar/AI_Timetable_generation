from ortools.sat.python import cp_model

# ===============================================
#  THIS IS YOUR UPGRADED, "SMART" SOLVER
# ===============================================
def generate_schedule(data, temporary_constraints=None, previous_schedule=None):
    """
    Generates a conflict-free timetable.
    
    If 'previous_schedule' is provided, it will try to
    minimize the number of changes from that schedule.
    """
    
    # --- 0. UNPACK DATA ---
    COURSES = data["COURSES"]
    FACULTY = data["FACULTY"]
    ROOMS = data["ROOMS"]
    STUDENT_ELECTIONS = data["STUDENT_ELECTIONS"]
    ALL_TIMESLOTS = data["ALL_TIMESLOTS"] # This is now a list of tuples, e.g., (0,0), (0,1)...
    
    print("Starting SMART solver...")
    model = cp_model.CpModel()
    
    # --- 1. DEFINE VARIABLES ---
    schedule = {}
    for course in COURSES:
        for faculty in FACULTY:
            for room in ROOMS:
                for timeslot in ALL_TIMESLOTS: # Use the list of tuples
                    # THIS IS THE CRITICAL BUG FIX LINE:
                    if (faculty["id"] in course["preferred_faculty"] and
                        timeslot in faculty["availability"] and
                        room["capacity"] >= course["enrollment"] and
                        course["type"] == room["type"]):  # <-- THIS IS THE FIX
                        
                        var_name = f'sched_c{course["id"]}_f{faculty["id"]}_r{room["id"]}_t{timeslot}'
                        schedule[(course["id"], faculty["id"], room["id"], timeslot)] = model.NewBoolVar(var_name)
    
    print(f"Created {len(schedule)} variables.")

    # --- 2. ADD HARD CONSTRAINTS (Same as before) ---

    # Constraint 1: Each course is taught exactly once 
    print("Adding course uniqueness constraint...")
    for course in COURSES:
        model.Add(
            sum(
                schedule.get((course["id"], faculty["id"], room["id"], timeslot))
                for faculty in FACULTY
                for room in ROOMS
                for timeslot in ALL_TIMESLOTS
                if (course["id"], faculty["id"], room["id"], timeslot) in schedule
            ) == 1
        )

    # Constraint 2: A faculty member can only be in one place at a time
    print("Adding faculty conflict constraint...")
    for faculty in FACULTY:
        for timeslot in ALL_TIMESLOTS:
            model.Add(
                sum(
                    schedule.get((course["id"], faculty["id"], room["id"], timeslot))
                    for course in COURSES
                    for room in ROOMS
                    if (course["id"], faculty["id"], room["id"], timeslot) in schedule
                ) <= 1
            )

    # Constraint 3: A room cannot host two classes at once
    print("Adding room conflict constraint...")
    for room in ROOMS:
        for timeslot in ALL_TIMESLOTS:
            model.Add(
                sum(
                    schedule.get((course["id"], faculty["id"], room["id"], timeslot))
                    for course in COURSES
                    for faculty in FACULTY
                    if (course["id"], faculty["id"], room["id"], timeslot) in schedule
                ) <= 1
            )

    # Constraint 4: Student conflict
    print("Creating student enrollment map...")
    student_enrollments = {}
    for election in STUDENT_ELECTIONS:
        student_id = election["student_id"]
        course_id = election["course_id"]
        if student_id not in student_enrollments:
            student_enrollments[student_id] = []
        student_enrollments[student_id].append(course_id)

    print("Adding student conflict constraint...")
    for student_id, enrolled_courses in student_enrollments.items():
        for timeslot in ALL_TIMESLOTS:
            model.Add(
                sum(
                    schedule.get((course_id, faculty["id"], room["id"], timeslot))
                    for course_id in enrolled_courses
                    for faculty in FACULTY
                    for room in ROOMS
                    if (course_id, faculty["id"], room["id"], timeslot) in schedule
                ) <= 1
            )
            
    # Constraint 5: Add temporary constraints from the UI
    if temporary_constraints:
        print(f"Adding {len(temporary_constraints)} temporary constraints...")
        for constraint in temporary_constraints:
            try:
                faculty_id = constraint["faculty_id"]
                day = constraint["day"]
                slot = constraint["slot"]
                
                for course in COURSES:
                    for room in ROOMS:
                        if (course["id"], faculty_id, room["id"], (day, slot)) in schedule:
                            model.Add(
                                schedule[(course["id"], faculty_id, room["id"], (day, slot))] == 0
                            )
            except Exception as e:
                print(f"Warning: Could not apply constraint {constraint}. Error: {e}")

    # ==========================================================
    #  NEW "SMART" UPGRADE: SOFT CONSTRAINTS
    # ==========================================================
    # This tells the AI to try its best to follow the previous schedule.
    
    if previous_schedule:
        print("Applying 'minimize changes' soft constraint...")
        
        reward_points = []
        
        # Create a map of the old schedule for easy lookup
        old_schedule_map = {}
        for item in previous_schedule:
            old_schedule_map[item['course']['id']] = (item['faculty']['id'], item['room']['id'], (item['day'], item['slot']))
        
        for course in COURSES:
            course_id = course['id']
            if course_id in old_schedule_map:
                old_faculty, old_room, old_timeslot = old_schedule_map[course_id]
                
                # Check if this assignment is still possible
                if (course_id, old_faculty, old_room, old_timeslot) in schedule:
                    reward_var = model.NewBoolVar(f'reward_c{course_id}')
                    model.Add(schedule[(course_id, old_faculty, old_room, old_timeslot)] == 1).OnlyEnforceIf(reward_var)
                    reward_points.append(reward_var)

        # Tell the AI: "Maximize the number of reward points!"
        model.Maximize(sum(reward_points))

    # --- 3. SOLVE AND PREPARE RESULTS ---
    print("\nStarting solver...")
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print("SOLUTION FOUND!")
        
        course_map = {c["id"]: c for c in COURSES}
        faculty_map = {f["id"]: f for f in FACULTY}
        room_map = {r["id"]: r for r in ROOMS}
        
        results = []
        for timeslot in ALL_TIMESLOTS:
            for course in COURSES:
                for faculty in FACULTY:
                    for room in ROOMS:
                        if (course["id"], faculty["id"], room["id"], timeslot) in schedule and \
                           solver.Value(schedule[(course["id"], faculty["id"], room["id"], timeslot)]) == 1:
                            
                            results.append({
                                "day": timeslot[0],
                                "slot": timeslot[1],
                                "course": course_map[course['id']],
                                "faculty": faculty_map[faculty['id']],
                                "room": room_map[room['id']]
                            })
        
        results.sort(key=lambda x: (x["day"], x["slot"]))
        return results
                            
    else:
        print("NO SOLUTION FOUND")
        return None

# ===============================================
#  TESTING BLOCK (No changes needed here)
# ===============================================
if __name__ == "__main__":
    
    print("--- RUNNING SOLVER IN TEST MODE ---")
    
    # (This test block is now too simple for our complex solver,
    #  but we leave it here. We will test from the API.)