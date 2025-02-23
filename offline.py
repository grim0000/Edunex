
import datetime
import json
import os
import uuid
from datetime import date, timedelta

from flask import Flask, render_template_string, request, redirect, url_for, flash # type: ignore


app = Flask(__name__)
app.secret_key = 'secret_key_here'  


DATA_DIR = "data"
NOTES_FILE = os.path.join(DATA_DIR, "notes.json")
os.makedirs(DATA_DIR, exist_ok=True)

TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
SCHEDULE_FILE = os.path.join(DATA_DIR, "schedule.json")
STUDENTS_FILE = os.path.join(DATA_DIR, "students.json")
ATTENDANCE_FILE = os.path.join(DATA_DIR, "attendance.json")
TESTS_FILE = os.path.join(DATA_DIR, "tests.json")


for file in [TASKS_FILE, SCHEDULE_FILE, STUDENTS_FILE, ATTENDANCE_FILE, TESTS_FILE, NOTES_FILE]:
    if not os.path.exists(file):
        with open(file, 'w') as f:
            json.dump({}, f)


def load_json(file):
    with open(file, 'r') as f:
        return json.load(f)

def save_json(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=4)


def get_today_schedule():
    schedule = load_json(SCHEDULE_FILE).get("today", {s: "" for s in ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']})
    items = [f"{time}: {activity}" for time, activity in schedule.items() if activity.strip()]
    return "\n".join(items) if items else "No activities scheduled today."

def check_upcoming_deadlines():
    tasks = load_json(TASKS_FILE)
    current_date = date.today().isoformat()
    future_date = (date.today() + timedelta(days=7)).isoformat()
    deadlines = [f"{t['name']} - Deadline: {t['deadline']}" for t in tasks.values() if t.get("deadline") and current_date <= t["deadline"] <= future_date]
    return "Your upcoming deadlines within 7 days are:\n" + "\n".join(deadlines) if deadlines else "No upcoming deadlines in the next 7 days."


def load_notes():
    return load_json(NOTES_FILE)

def save_note(note_id, title, content, category):
    notes = load_json(NOTES_FILE)
    notes[note_id] = {
        "title": title,
        "content": content,
        "category": category,
        "createdAt": datetime.datetime.now().isoformat()
    }
    save_json(NOTES_FILE, notes)

def delete_note(note_id):
    notes = load_json(NOTES_FILE)
    if note_id in notes:
        del notes[note_id]
        save_json(NOTES_FILE, notes)


base_template = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Teacher Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body {
      font-family: 'Inter', sans-serif;
      background: linear-gradient(135deg, #f3e8ff, #dbeafe);
      color: #1f2937;
    }
    .sidebar {
      background: linear-gradient(to bottom, #8b5cf6, #6d28d9);
      transition: width 0.3s ease;
    }
    .sidebar a {
      transition: background-color 0.2s ease, transform 0.2s ease;
    }
    .sidebar a:hover {
      background-color: #7c3aed;
      transform: translateX(5px);
    }
    .header {
      background: linear-gradient(to right, #8b5cf6, #d8b4fe);
      box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .card {
      background: white;
      border-radius: 12px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .card:hover {
      transform: translateY(-5px);
      box-shadow: 0 6px 25px rgba(0, 0, 0, 0.1);
    }
    .fade-in {
      animation: fadeIn 0.5s ease-in-out;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(-10px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .btn {
      background: linear-gradient(to right, #8b5cf6, #a78bfa);
      color: white;
      padding: 8px 16px;
      border-radius: 8px;
      transition: background 0.3s ease, transform 0.2s ease;
    }
    .btn:hover {
      background: linear-gradient(to right, #7c3aed, #9f67fa);
      transform: scale(1.05);
    }
    .note-card {
      border-left: 4px solid;
      border-color: {{ 'var(--category-color)' }};
    }
  </style>
</head>
<body class="min-h-screen flex flex-col">
  <div class="flex flex-1">
    <aside class="sidebar w-64 p-4 text-white shadow-lg">
      <nav>
        <ul class="space-y-3">
          <li><a href="{{ url_for('dashboard') }}" class="block p-3 rounded-lg">Dashboard</a></li>
          <li><a href="{{ url_for('attendance') }}" class="block p-3 rounded-lg">Attendance</a></li>
          <li><a href="{{ url_for('today_schedule') }}" class="block p-3 rounded-lg">Today’s Schedule</a></li>
          <li><a href="{{ url_for('pending_tasks') }}" class="block p-3 rounded-lg">Pending Tasks</a></li>
          <li><a href="{{ url_for('notes') }}" class="block p-3 rounded-lg">Notes</a></li>
        </ul>
      </nav>
    </aside>
    <div class="flex-1 flex flex-col">
      <header class="header flex items-center justify-between p-6 text-white">
        <h1 class="text-3xl font-bold">{{ active_page|capitalize }}</h1>
      </header>
      <main class="flex-1 p-6 fade-in">
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            <div class="mb-6 space-y-2">
              {% for msg in messages %}
                <div class="p-3 bg-green-100 text-green-800 rounded-lg shadow">{{ msg }}</div>
              {% endfor %}
            </div>
          {% endif %}
        {% endwith %}
        {{ content|safe }}
      </main>
    </div>
  </div>
</body>
</html>
"""


@app.route('/')
@app.route('/dashboard')
def dashboard():
    # Today’s Schedule
    schedule = load_json(SCHEDULE_FILE).get("today", {s: "" for s in ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']})
    num_activities = sum(1 for act in schedule.values() if act.strip())
    schedule_items = "".join([f"<li class='py-1'>{time}: {act}</li>" for time, act in schedule.items() if act.strip()])

    # Pending Tasks
    tasks = load_json(TASKS_FILE)
    pending_tasks_count = sum(1 for t in tasks.values() if t.get("status") == "pending")
    pending_tasks = "".join([f"<li class='py-1'>{t['name']} - Deadline: {t.get('deadline', 'None')}</li>" for t in tasks.values() if t.get("status") == "pending"])

    # Attendance Alerts
    students = load_json(STUDENTS_FILE)
    attendance = load_json(ATTENDANCE_FILE)
    alert_count = 0
    attendance_alerts = ""
    for sid, s in students.items():
        student_class = s.get("class")
        if not student_class:
            continue
        class_att = {k: v for k, v in attendance.items() if k.endswith(f"_{student_class}")}
        total = len(class_att)
        if total == 0:
            continue
        present = sum(1 for d in class_att.values() if d.get(sid, False))
        percentage = (present / total) * 100
        if percentage < 50:
            alert_count += 1
            attendance_alerts += f"<li class='py-1'>{s.get('name')} - {percentage:.1f}%</li>"

    # Upcoming Deadlines
    current_date = date.today().isoformat()
    future_date = (date.today() + timedelta(days=7)).isoformat()
    upcoming_deadlines_count = sum(1 for t in tasks.values() if t.get("deadline") and current_date <= t["deadline"] <= future_date)
    deadlines = "".join([f"<li class='py-1'>{t['name']} - {t['deadline']}</li>" for t in tasks.values() if t.get("deadline") and current_date <= t["deadline"] <= future_date])

    content = f"""
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
      <!-- Today's Schedule -->
      <div class="card p-6">
        <h2 class="text-xl font-semibold mb-4">Today’s Schedule ({num_activities})</h2>
        <ul class="list-disc pl-5">{schedule_items if schedule_items else '<p>No activities today.</p>'}</ul>
        
      </div>

      <!-- Pending Tasks -->
      <div class="card p-6">
        <h2 class="text-xl font-semibold mb-4">Pending Tasks ({pending_tasks_count})</h2>
        <ul class="list-disc pl-5">{pending_tasks if pending_tasks else '<p>No pending tasks.</p>'}</ul>
        
      </div>

      <!-- Attendance Alerts -->
      <div class="card p-6">
        <h2 class="text-xl font-semibold mb-4">Attendance Alerts ({alert_count})</h2>
        <ul class="list-disc pl-5">{attendance_alerts if attendance_alerts else '<p>No alerts.</p>'}</ul>
        
      </div>

      <!-- Upcoming Deadlines -->
      <div class="card p-6">
        <h2 class="text-xl font-semibold mb-4">Upcoming Deadlines ({upcoming_deadlines_count})</h2>
        <ul class="list-disc pl-5">{deadlines if deadlines else '<p>No deadlines soon.</p>'}</ul>
        
      </div>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='dashboard')


@app.route('/notes', methods=['GET', 'POST'])
def notes():
    notes = load_json(NOTES_FILE)
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_note':
            note_id = str(uuid.uuid4())
            title = request.form.get('title')
            content = request.form.get('content')
            category = request.form.get('category', 'General')
            save_note(note_id, title, content, category)
            flash("Note added successfully!")
        elif action == 'delete_note':
            note_id = request.form.get('note_id')
            delete_note(note_id)
            flash("Note deleted!")
        return redirect(url_for('notes'))

    
    category_colors = {
        "General": "#6b7280",  # Gray
        "Urgent": "#ef4444",   # Red
        "Planning": "#3b82f6", # Blue
        "Ideas": "#10b981"     # Green
    }

    notes_html = "".join([f"""
    <div class="card p-4 mb-4 note-card" style="--category-color: {category_colors.get(n['category'], '#6b7280')}">
      <div class="flex justify-between items-center mb-2">
        <h3 class="text-lg font-semibold">{n['title']}</h3>
        <span class="text-sm text-gray-500">{n['category']} • {n['createdAt'][:10]}</span>
      </div>
      <p class="text-gray-700">{n['content']}</p>
      <form method="post" class="mt-2">
        <input type="hidden" name="action" value="delete_note">
        <input type="hidden" name="note_id" value="{nid}">
        <button type="submit" class="text-red-500 hover:text-red-700 text-sm">Delete</button>
      </form>
    </div>
    """ for nid, n in notes.items()])

    content = f"""
    <div class="card p-6">
      <h2 class="text-2xl font-bold mb-4">Notes</h2>
      <form method="post" class="mb-6">
        <input type="hidden" name="action" value="add_note">
        <div class="mb-4">
          <label class="block text-sm font-medium mb-1">Title</label>
          <input type="text" name="title" placeholder="Note Title" class="w-full p-2 border rounded" required>
        </div>
        <div class="mb-4">
          <label class="block text-sm font-medium mb-1">Content</label>
          <textarea name="content" placeholder="Write your note here..." class="w-full p-2 border rounded h-32" required></textarea>
        </div>
        <div class="mb-4">
          <label class="block text-sm font-medium mb-1">Category</label>
          <select name="category" class="w-full p-2 border rounded">
            <option value="General">General</option>
            <option value="Urgent">Urgent</option>
            <option value="Planning">Planning</option>
            <option value="Ideas">Ideas</option>
          </select>
        </div>
        <button type="submit" class="btn">Add Note</button>
      </form>
      <div class="space-y-4">
        {notes_html if notes_html else '<p class="text-gray-500">No notes yet. Add one above!</p>'}
      </div>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='notes')


@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    classes = ['CSE1', 'CSE2', 'CSE3', 'IS', 'AIML']
    selected_class = request.args.get('class_name', classes[0])
    date_str = request.args.get('date', date.today().isoformat())
    doc_id = f"{date_str}_{selected_class}"
    
    attendance = load_json(ATTENDANCE_FILE)
    students = load_json(STUDENTS_FILE)
    class_students = {sid: s for sid, s in students.items() if s.get("class") == selected_class}
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update':
            student_id = request.form.get('student_id')
            status = request.form.get('status') == 'present'
            att_data = attendance.get(doc_id, {})
            att_data[student_id] = status
            attendance[doc_id] = att_data
            save_json(ATTENDANCE_FILE, attendance)
            flash("Attendance updated!")
        elif action == 'save':
            att_data = {sid: request.form.get(sid, 'absent') == 'present' for sid in request.form if sid not in ['action', 'date', 'class_name']}
            attendance[doc_id] = att_data
            save_json(ATTENDANCE_FILE, attendance)
            flash("Attendance saved!")
        return redirect(url_for('attendance', date=date_str, class_name=selected_class))
    
    att_data = attendance.get(doc_id, {})
    rows = "".join([f"""
    <tr>
      <td class="p-4 border-b">{s.get('name')}</td>
      <td class="p-4 border-b">{'Present' if att_data.get(sid, False) else 'Absent'}</td>
      <td class="p-4 border-b">
        <label class="mr-4"><input type="radio" name="{sid}" value="present" {'checked' if att_data.get(sid, False) else ''} required> Present</label>
        <label><input type="radio" name="{sid}" value="absent" {'checked' if not att_data.get(sid, False) else ''}> Absent</label>
      </td>
    </tr>
    """ for sid, s in class_students.items()])
    
    class_options = "".join([f'<option value="{c}" {"selected" if c == selected_class else ""}>{c}</option>' for c in classes])
    content = f"""
    <div class="card p-6">
      <form method="get" class="mb-4 flex gap-4 items-center">
        <label class="font-medium">Select Class:</label>
        <select name="class_name" class="border p-2 rounded">{class_options}</select>
        <input type="date" name="date" value="{date_str}" class="border p-2 rounded">
        <button type="submit" class="btn">Go</button>
      </form>
      <form method="post">
        <input type="hidden" name="action" value="save">
        <input type="hidden" name="date" value="{date_str}">
        <input type="hidden" name="class_name" value="{selected_class}">
        <table class="w-full border-collapse bg-white rounded-lg shadow">
          <thead>
            <tr class="bg-gray-100">
              <th class="p-4 text-left border-b">Student Name</th>
              <th class="p-4 text-left border-b">Current Status</th>
              <th class="p-4 text-left border-b">Mark Attendance</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        <button type="submit" class="btn mt-4">Save All</button>
      </form>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='attendance')

@app.route('/today-schedule', methods=['GET', 'POST'])
def today_schedule():
    schedule_data = load_json(SCHEDULE_FILE).get("today", {s: "" for s in ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']})
    
    if request.method == 'POST':
        sched_data = {slot: request.form.get(slot, '') for slot in schedule_data.keys()}
        schedule = load_json(SCHEDULE_FILE)
        schedule["today"] = sched_data
        save_json(SCHEDULE_FILE, schedule)
        flash("Schedule saved!")
        return redirect(url_for('today_schedule'))
    
    rows = "".join([f"""
    <tr>
      <td class="p-4 border-b">{slot}</td>
      <td class="p-4 border-b"><input type="text" name="{slot}" value="{act}" class="w-full p-2 border rounded"></td>
    </tr>
    """ for slot, act in schedule_data.items()])
    content = f"""
    <div class="card p-6">
      <h2 class="text-2xl font-bold mb-4">Today's Schedule</h2>
      <form method="post">
        <table class="w-full border-collapse bg-white rounded-lg shadow">
          <thead>
            <tr class="bg-gray-100">
              <th class="p-4 text-left border-b">Time</th>
              <th class="p-4 text-left border-b">Activity</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        <button type="submit" class="btn mt-4">Save Schedule</button>
      </form>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='today-schedule')

@app.route('/pending-tasks', methods=['GET', 'POST'])
def pending_tasks():
    tasks = load_json(TASKS_FILE)
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_task':
            task_id = str(uuid.uuid4())
            tasks[task_id] = {
                "name": request.form.get('task_name'),
                "deadline": request.form.get('task_deadline') or None,
                "status": "pending",
                "highPriority": request.form.get('high_priority') == 'on',
                "createdAt": datetime.datetime.now().isoformat()
            }
            save_json(TASKS_FILE, tasks)
            flash("Task added!")
        elif action == 'toggle_status':
            task_id = request.form.get('task_id')
            if task_id in tasks:
                tasks[task_id]["status"] = 'completed' if tasks[task_id].get('status') == 'pending' else 'pending'
                save_json(TASKS_FILE, tasks)
                flash("Task status toggled!")
        return redirect(url_for('pending_tasks'))
    
    tasks_html = "".join([f"""
    <li class="flex items-center justify-between p-3 bg-gray-50 rounded hover:bg-gray-100">
      <div class="flex items-center space-x-3">
        <form method="post">
          <input type="hidden" name="action" value="toggle_status">
          <input type="hidden" name="task_id" value="{tid}">
          <input type="checkbox" {'checked' if t['status'] == 'completed' else ''} onchange="this.form.submit()" class="h-4 w-4">
        </form>
        <span class="{'line-through text-gray-500' if t['status'] == 'completed' else ''}">{t['name']} ({t.get('deadline', 'No deadline')})</span>
      </div>
    </li>
    """ for tid, t in tasks.items()])
    
    content = f"""
    <div class="card p-6">
      <h2 class="text-2xl font-bold mb-4">Pending Tasks</h2>
      <form method="post" class="mb-4 flex gap-2">
        <input type="hidden" name="action" value="add_task">
        <input type="text" name="task_name" placeholder="Task Name" class="border p-2 rounded flex-1" required>
        <input type="date" name="task_deadline" class="border p-2 rounded">
        <label class="flex items-center"><input type="checkbox" name="high_priority" class="mr-2"> High Priority</label>
        <button type="submit" class="btn">Add Task</button>
      </form>
      <ul class="space-y-2">{tasks_html if tasks_html else '<p>No tasks.</p>'}</ul>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='pending-tasks')


if __name__ == '__main__':
    app.run(debug=True, port=5000)