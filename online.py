import json
import time
import os
import uuid
import aiohttp
import asyncio
from functools import lru_cache, wraps
from datetime import date, datetime, timedelta

from flask import Flask, render_template_string, request, redirect, url_for, flash, session
import firebase_admin
from firebase_admin import credentials, firestore, storage
from werkzeug.security import generate_password_hash, check_password_hash
from huggingface_hub import InferenceClient
# Firebase Initialization
# -------------------------------
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'storageBucket': "firstproject-5211a.firebasestorage.app"
})
db = firestore.client()
bucket = storage.bucket()

# -------------------------------
# Flask App Initialization
# -------------------------------
app = Flask(__name__)
app.secret_key = 'secret_key_here'
# -------------------------------
# Hugging Face API Setup
# -------------------------------
# Replace with your Hugging Face API token
HF_API_TOKEN = "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"
client = InferenceClient(token=HF_API_TOKEN)
CHATS_DIR = "chats"
os.makedirs(CHATS_DIR, exist_ok=True)
# Use a conversational model available via the API (e.g., distilgpt2 or a LLaMA variant if accessible)
MODEL_NAME = "meta-llama/Llama-3.2-3B-Instruct"  # Switch to "meta-llama/Llama-2-7b-chat-hf" if you have access
def list_pending_tasks():
    pending_tasks_query = db.collection("tasks").where("status", "==", "pending").order_by("deadline").limit(50).stream()
    tasks = [f"{t['name']} - Deadline: {t.get('deadline', 'No deadline')}" for t in (doc.to_dict() for doc in pending_tasks_query)]
    return "Your pending tasks are:\n" + "\n".join(tasks) if tasks else "No pending tasks."

def suggest_prioritization():
    pending_tasks_query = db.collection("tasks").where("status", "==", "pending").order_by("deadline").limit(50).stream()
    tasks = [{"name": t["name"], "deadline": t.get("deadline"), "highPriority": t.get("highPriority", False)} for t in (doc.to_dict() for doc in pending_tasks_query)]
    
    sched_ref = db.collection("schedule").document("today")
    doc = sched_ref.get()
    sched_data = doc.to_dict() if doc.exists else {s: "" for s in ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']}
    num_activities = sum(1 for act in sched_data.values() if act.strip())
    
    if not tasks and num_activities == 0:
        return "You have no tasks or activities to prioritize today. Enjoy a relaxed day!"
    
    priorities = []
    if tasks:
        # Prioritize by deadline (soonest first) and high priority
        sorted_tasks = sorted(tasks, key=lambda x: (x["deadline"] is None, x["deadline"] if x["deadline"] else "9999-12-31", not x["highPriority"]))
        priorities.extend([f"{i+1}. {task['name']} (Deadline: {task['deadline'] if task['deadline'] else 'No deadline'}, {'High Priority' if task['highPriority'] else 'Normal Priority'})" for i, task in enumerate(sorted_tasks[:5])])
    
    if num_activities > 0:
        priorities.append(f"Also focus on your {num_activities} scheduled activities today.")
    
    return "I recommend prioritizing the following today:\n" + "\n".join(priorities)
def get_today_schedule():
    sched_ref = db.collection("schedule").document("today")
    doc = sched_ref.get()
    sched_data = doc.to_dict() if doc.exists else {s: "" for s in ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']}
    schedule_items = [f"{time}: {activity}" for time, activity in sched_data.items() if activity.strip()]
    return "\n".join(schedule_items) if schedule_items else "No activities scheduled today."

def get_student_attendance(student_name):
    students_ref = db.collection("students").stream()
    for student_doc in students_ref:
        student = student_doc.to_dict()
        if student.get("name", "").lower() == student_name.lower():
            sid = student_doc.id
            student_class = student.get("class")
            if not student_class:
                return "Student class not found."
            att_docs = [doc for doc in db.collection("attendance").stream() if doc.id.endswith(f"_{student_class}")]
            total = len(att_docs)
            if total == 0:
                return "No attendance records found."
            present = sum(1 for doc in att_docs if doc.to_dict().get(sid, False))
            percentage = (present / total) * 100 if total > 0 else 0
            return f"{student_name} has {percentage:.1f}% attendance."
    return "Student not found."

def mark_attendance(student_name, status):
    today = date.today().strftime("%Y-%m-%d")
    students_ref = db.collection("students").stream()
    for student_doc in students_ref:
        student = student_doc.to_dict()
        if student.get("name", "").lower() == student_name.lower():
            sid = student_doc.id
            student_class = student.get("class")
            if not student_class:
                return "Student class not found."
            doc_id = f"{today}_{student_class}"
            att_ref = db.collection("attendance").document(doc_id)
            att_doc = att_ref.get()
            att_data = att_doc.to_dict() if att_doc.exists else {}
            att_data[sid] = status.lower() == "present"
            att_ref.set(att_data)
            return f"Marked {student_name} as {'present' if status.lower() == 'present' else 'absent'} for today."
    return "Student not found."

def check_for_tests():
    today = date.today().isoformat()
    tests_ref = db.collection("tests").where("date", ">=", today).order_by("date").limit(5).stream()
    tests = [{"subject": t["subject"], "date": t["date"], "time": t["time"]} for t in (doc.to_dict() for doc in tests_ref)]
    if tests:
        return "You have the following tests scheduled:\n" + "\n".join([f"{t['subject']} on {t['date']} at {t['time']}" for t in tests])
    return "No tests scheduled in the near future."

def assess_workload_stress():
    sched_ref = db.collection("schedule").document("today")
    doc = sched_ref.get()
    sched_data = doc.to_dict() if doc.exists else {s: "" for s in ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']}
    num_activities = sum(1 for act in sched_data.values() if act.strip())
    
    pending_tasks_query = db.collection("tasks").where("status", "==", "pending").limit(50)
    pending_tasks_count = len(list(pending_tasks_query.stream()))
    
    current_date = date.today().isoformat()
    future_date = (date.today() + timedelta(days=7)).isoformat()
    upcoming_deadlines_query = db.collection("tasks").where("deadline", ">=", current_date).where("deadline", "<=", future_date).limit(50)
    upcoming_deadlines_count = len(list(upcoming_deadlines_query.stream()))
    
    stress_level = "low"
    if num_activities > 5 or pending_tasks_count > 10 or upcoming_deadlines_count > 5:
        stress_level = "moderate"
    if num_activities > 8 or pending_tasks_count > 15 or upcoming_deadlines_count > 10:
        stress_level = "high"
    
    return f"Your workload today is {stress_level} stress. You have {num_activities} activities, {pending_tasks_count} pending tasks, and {upcoming_deadlines_count} upcoming deadlines within 7 days."
def check_upcoming_deadlines():
    current_date = date.today().isoformat()
    future_date = (date.today() + timedelta(days=7)).isoformat()
    upcoming_deadlines_query = db.collection("tasks").where("deadline", ">=", current_date).where("deadline", "<=", future_date).order_by("deadline").limit(50).stream()
    deadlines = [f"{t['name']} - Deadline: {t['deadline']}" for t in (doc.to_dict() for doc in upcoming_deadlines_query)]
    return "Your upcoming deadlines within 7 days are:\n" + "\n".join(deadlines) if deadlines else "No upcoming deadlines in the next 7 days."

def generate_study_tips(student_name):
    students_ref = db.collection("students").stream()
    for student_doc in students_ref:
        student = student_doc.to_dict()
        if student.get("name", "").lower() == student_name.lower():
            sid = student_doc.id
            student_class = student.get("class")
            if not student_class:
                return "Student class not found."
            att_docs = [doc for doc in db.collection("attendance").stream() if doc.id.endswith(f"_{student_class}")]
            total = len(att_docs)
            if total == 0:
                return "No attendance records found for study tips."
            present = sum(1 for doc in att_docs if doc.to_dict().get(sid, False))
            percentage = (present / total) * 100 if total > 0 else 0
            
            performance_ref = db.collection("students").document(sid).collection("performance").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(1).stream()
            performance = next(performance_ref, None)
            performance_data = performance.to_dict() if performance else {}
            score = performance_data.get("average_score", 0)
            
            tips = []
            if percentage < 50:
                tips.append("Encourage regular attendance and provide catch-up resources.")
            if score < 60:
                tips.append("Focus on foundational concepts and offer extra practice problems.")
            elif score < 80:
                tips.append("Review challenging topics and provide advanced exercises.")
            else:
                tips.append("Maintain momentum with challenging projects and peer discussions.")
            
            return f"Study tips for {student_name}:\n" + "\n".join(tips) if tips else "No specific tips needed—great performance!"
    return "Student not found."

def notify_overdue_tasks():
    current_date = date.today().isoformat()
    overdue_query = db.collection("tasks").where("deadline", "<", current_date).where("status", "==", "pending").order_by("deadline", direction=firestore.Query.DESCENDING).limit(50).stream()
    overdue_tasks = [f"{t['name']} - Deadline: {t['deadline']}" for t in (doc.to_dict() for doc in overdue_query)]
    return "You have the following overdue tasks:\n" + "\n".join(overdue_tasks) if overdue_tasks else "No overdue tasks."

def estimate_time_for_tasks():
    pending_tasks_query = db.collection("tasks").where("status", "==", "pending").limit(50).stream()
    tasks = [t for t in (doc.to_dict() for doc in pending_tasks_query)]
    total_time = 0
    for task in tasks:
        # Simple estimation: 30 minutes per task, adjust based on complexity or tags if available
        complexity = task.get("complexity", "medium")
        if complexity == "high":
            total_time += 60  # 1 hour
        elif complexity == "low":
            total_time += 15  # 15 minutes
        else:
            total_time += 30  # 30 minutes (default)
    
    hours = total_time // 60
    minutes = total_time % 60
    return f"Your pending tasks are estimated to take {hours} hours and {minutes} minutes to complete today."

def suggest_break_times():
    sched_ref = db.collection("schedule").document("today")
    doc = sched_ref.get()
    sched_data = doc.to_dict() if doc.exists else {s: "" for s in ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']}
    activities = [(time, activity) for time, activity in sched_data.items() if activity.strip()]
    
    if not activities:
        return "No activities scheduled today. You can take breaks anytime!"
    
    break_times = []
    current_time = datetime.strptime("09:00", "%H:%M")
    end_time = datetime.strptime("15:00", "%H:%M")
    
    while current_time < end_time:
        next_activity_time = None
        for time, _ in activities:
            activity_time = datetime.strptime(time, "%H:%M")
            if activity_time > current_time and (next_activity_time is None or activity_time < next_activity_time):
                next_activity_time = activity_time
        if next_activity_time:
            break_duration = (next_activity_time - current_time).total_seconds() / 60
            if break_duration > 15:  # Suggest breaks longer than 15 minutes
                break_times.append(f"Take a break from {current_time.strftime('%H:%M')} to {next_activity_time.strftime('%H:%M')} ({break_duration:.0f} minutes)")
            current_time = next_activity_time
        else:
            break_times.append(f"Take a break from {current_time.strftime('%H:%M')} to 15:00 (remaining time)")
            break
    
    return "Suggested break times today:\n" + "\n".join(break_times) if break_times else "No optimal break times available today due to a tight schedule."
def load_chat_history(user_id):
    user_email = session.get('user', {}).get('email', 'default_user')
    file_path = os.path.join(CHATS_DIR, f"{user_email}_chat_history.json")
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return json.load(f)
    return []

def save_chat_history(user_id, history):
    user_email = session.get('user', {}).get('email', 'default_user')
    file_path = os.path.join(CHATS_DIR, f"{user_email}_chat_history.json")
    with open(file_path, 'w') as f:
        json.dump(history, f, indent=4)

async def get_chatbot_response_async(user_input, context_data=""):
    # Combine context, history, and user input for better context
    history_text = "\n".join([f"User: {h['user']}\nAI: {h['bot']}" for h in history[-5:]]) if history else "" # type: ignore
    
    # Parse user input for specific intents
    user_input_lower = user_input.lower()
    response = None
    
    # Handle schedule queries (existing)
    if any(keyword in user_input_lower for keyword in ["schedule", "today's schedule", "what is my schedule"]):
        schedule = get_today_schedule()
        if "list it out" in user_input_lower:
            numbered_schedule = "\n".join([f"{i+1}. {item}" for i, item in enumerate(schedule.split("\n") if schedule else []) if item.strip()])
            response = f"Good morning! Your schedule for today is as follows:\n{numbered_schedule}"
        else:
            response = f"Good morning! You have a schedule for today. Would you like me to list it out? Here’s a brief overview: {schedule[:50]}{'...' if len(schedule) > 50 else ''}"
    
    # Handle attendance queries (existing)
    elif "how much is" in user_input_lower and "attendance" in user_input_lower:
        student_name = user_input_lower.split("how much is")[1].split("attendance")[0].strip()
        response = get_student_attendance(student_name) or "I couldn’t find that student’s attendance. Could you check the name?"

    # Handle marking attendance (existing)
    elif "mark" in user_input_lower and ("present" in user_input_lower or "absent" in user_input_lower):
        parts = user_input_lower.split("mark")
        if len(parts) > 1:
            student_part = parts[1].split("present" if "present" in user_input_lower else "absent")[0].strip()
            student_name = student_part.replace("the", "").strip()
            status = "present" if "present" in user_input_lower else "absent"
            response = mark_attendance(student_name, status)

    # Handle test queries (existing)
    elif "do i have a test" in user_input_lower or "are there any tests" in user_input_lower:
        response = check_for_tests()

    # Handle workload stress queries (existing)
    elif "is my work stressful today" in user_input_lower:
        response = assess_workload_stress()

    # New functionalities
    # List pending tasks
    elif "what are my pending tasks" in user_input_lower or "list my pending tasks" in user_input_lower:
        response = list_pending_tasks()

    # Suggest prioritization
    elif "what should i prioritize today" in user_input_lower:
        response = suggest_prioritization()

    # Check upcoming deadlines
    elif "what are my upcoming deadlines" in user_input_lower:
        response = check_upcoming_deadlines()

    # Generate study tips
    elif "what study tips for" in user_input_lower:
        student_name = user_input_lower.split("what study tips for")[1].strip()
        response = generate_study_tips(student_name) or "I couldn’t find study tips for that student. Please check the name."

    # Notify about overdue tasks
    elif "do i have any overdue tasks" in user_input_lower:
        response = notify_overdue_tasks()

    # Estimate time for tasks
    elif "how much time will my tasks take today" in user_input_lower:
        response = estimate_time_for_tasks()

    # Suggest break times
    elif "when should i take a break today" in user_input_lower:
        response = suggest_break_times()

    # Default conversational response if no specific intent is matched
    if not response:
        prompt = (
            f"You are a helpful, polite, and accurate AI assistant for a teacher. "
            f"Use the following context to provide insights: {context_data}\n"
            f"Previous conversation (if any): {history_text}\n"
            f"User: {user_input}\n"
            f"AI (be concise, polite, relevant, and list items like schedules, tasks, tests, or deadlines if asked):"
        )
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
                url = f"https://api-inference.huggingface.co/models/{MODEL_NAME}"
                payload = {
                    "inputs": prompt,
                    "parameters": {"max_new_tokens": 300, "temperature": 0.7, "top_p": 0.9, "do_sample": True}
                }
                async with session.post(url, json=payload, headers=headers) as response:
                    result = await response.json()
                    response_text = result[0]["generated_text"].strip() if "generated_text" in result[0] else "Sorry, I couldn’t generate a response."
                    if response_text.startswith("AI:"):
                        response_text = response_text[3:].strip()
                    return response_text
        except Exception as e:
            return f"Sorry, I encountered an error: {str(e)}"
    
    return response
def get_chatbot_response(user_input, context_data="", history=[]):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    response = loop.run_until_complete(get_chatbot_response_async(user_input, context_data, history))
    loop.close()
    return response
# Helper function to get chatbot response via API
def get_chatbot_response(user_input, context_data=""):
    # Simple check for rude input (expand as needed)
    rude_words = ["rude", "stupid", "bad"]  # Add more as needed
    if any(word in user_input.lower() for word in rude_words):
        return "I’m sorry, I can’t respond to that. How can I assist you today in a polite and helpful way?"
    
    prompt = (
        f"You are a helpful and polite AI assistant for a teacher. "
        f"Use the following context to provide insights: {context_data}\n"
        f"User: {user_input}\n"
        f"AI (be concise, polite, and relevant):"
    )
    try:
        response = client.text_generation(
            prompt,
            model=MODEL_NAME,
            max_new_tokens=150,
            temperature=0.7,
            top_p=0.9,
            do_sample=True,
            stop_sequences=["\n", "AI:"]
        )
        return response.strip()
    except Exception as e:
        return f"Sorry, I encountered an error: {str(e)}"
# -------------------------------
# Login Required Decorator
# -------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash("Please log in first.")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# -------------------------------
# Base Template with Violet Theme, MacOS-Inspired UI, and Animations
# -------------------------------
base_template = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Teacher Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    .fade-in { animation: fadeIn 0.5s ease-in-out; }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(-10px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .macos { backdrop-filter: blur(10px); }
  </style>
</head>
<body class="bg-violet-50 text-gray-900 transition-all duration-300">
  <div class="flex flex-col min-h-screen">
    <header class="flex items-center justify-between p-4 bg-violet-600 text-white macos shadow-lg">
      <h1 class="text-3xl font-bold">{{ active_page|capitalize }}</h1>
      <div class="flex items-center space-x-4">
        {% if session.get('user') %}
          <span class="hidden sm:block text-lg">{{ session['user']['name'] }}</span>
          <a href="{{ url_for('profile') }}">
            <img src="{{ session['user'].get('avatar', 'https://via.placeholder.com/40') }}" alt="Profile" class="w-10 h-10 rounded-full border-2 border-white transition-all duration-300 hover:scale-105">
          </a>
          <a href="{{ url_for('logout') }}" class="text-white underline">Logout</a>
        {% else %}
          <a href="{{ url_for('login') }}" class="text-white underline">Login</a>
        {% endif %}
      </div>
    </header>
    <div class="flex flex-1">
      <aside class="w-64 p-4 bg-violet-500 text-white macos shadow-md">
        <div class="mb-4">
          <a href="{{ url_for('dashboard') }}" class="block text-xl font-bold">Dashboard</a>
        </div>
        <nav>
          <ul class="space-y-2">
            <li><a href="{{ url_for('dashboard') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Dashboard</a></li>
            <li><a href="{{ url_for('attendance') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Attendance</a></li>
            <li><a href="{{ url_for('today_schedule') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Today’s Schedule</a></li>
            <li><a href="{{ url_for('pending_tasks') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Pending Tasks</a></li>
            <li><a href="{{ url_for('student_alerts') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Student Alerts</a></li>
            <li><a href="{{ url_for('upcoming_deadlines') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Upcoming Deadlines</a></li>
            <li><a href="{{ url_for('student_forum') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Student Forum</a></li>
            <li><a href="{{ url_for('assignments_tests') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Submissions</a></li>
            <li><a href="{{ url_for('student_performance') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Student Performance</a></li>
            <li><a href="{{ url_for('students') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Student Management</a></li>
            <li><a href="{{ url_for('messaging') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Messaging</a></li>
            <li><a href="{{ url_for('ai_insights') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">AI Insights</a></li>
            <li><a href="{{ url_for('settings') }}" class="block p-2 hover:bg-violet-700 rounded transition-colors">Settings</a></li>
          </ul>
        </nav>
      </aside>
      <main class="flex-1 p-6 fade-in">
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            <div class="mb-4 space-y-2">
              {% for msg in messages %}
                <div class="p-2 bg-green-200 text-green-800 rounded">{{ msg }}</div>
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
# -------------------------------
# AI Insights Endpoint
# -------------------------------

@app.route('/ai-insights', methods=['GET', 'POST'])
@login_required
def ai_insights():
    # Fetch dashboard data for context (use existing get_dashboard_stats)
    @lru_cache(maxsize=128)
    def get_dashboard_stats():
        sched_ref = db.collection("schedule").document("today")
        doc = sched_ref.get()
        sched_data = doc.to_dict() if doc.exists else {s: "" for s in ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']}
        num_activities = sum(1 for act in sched_data.values() if act.strip())
        
        pending_tasks_query = db.collection("tasks").where("status", "==", "pending").limit(50)
        pending_tasks_count = len(list(pending_tasks_query.stream()))
        
        students_ref = db.collection("students").stream()
        alert_count = 0
        for student_doc in students_ref:
            student = student_doc.to_dict()
            sid = student_doc.id
            student_class = student.get("class")
            if not student_class:
                continue
            att_docs = [doc for doc in db.collection("attendance").stream() if doc.id.endswith(f"_{student_class}")]
            total = len(att_docs)
            if total == 0:
                continue
            present = sum(1 for doc in att_docs if doc.to_dict().get(sid, False))
            percentage = (present / total) * 100
            if percentage < 50:
                alert_count += 1
        
        current_date = date.today().isoformat()
        future_date = (date.today() + timedelta(days=7)).isoformat()
        upcoming_deadlines_query = db.collection("tasks").where("deadline", ">=", current_date).where("deadline", "<=", future_date).limit(50)
        upcoming_deadlines_count = len(list(upcoming_deadlines_query.stream()))
        
        # Get today's schedule details
        schedule_details = get_today_schedule()
        
        return (num_activities, pending_tasks_count, alert_count, upcoming_deadlines_count, schedule_details)

    num_activities, pending_tasks_count, alert_count, upcoming_deadlines_count, schedule_details = get_dashboard_stats()

    # Context string for the AI
    context = (
        f"Teacher dashboard stats: {num_activities} activities today, "
        f"{pending_tasks_count} pending tasks, {alert_count} student alerts, "
        f"{upcoming_deadlines_count} upcoming deadlines within 7 days. "
        f"Today's schedule: {schedule_details}"
    )
    
    # Load chat history for the current user
    user_id = session.get('user', {}).get('email', 'default_user')
    chat_history = load_chat_history(user_id)
    
    if request.method == 'POST':
        user_input = request.form.get('message')
        if user_input:
            if user_input.lower() == 'reset':
                chat_history = []
                save_chat_history(user_id, chat_history)
                flash("Chat history reset!")
            else:
                # Get AI response using the full chat history
                response = get_chatbot_response(user_input, context)
                chat_history.append({"user": user_input, "bot": response})
                save_chat_history(user_id, chat_history[-50:])  # Limit to last 50 messages
            return redirect(url_for('ai_insights'))
    
    chat_html = ""
    for entry in chat_history:
        chat_html += f"""
        <div class="mb-4">
          <div class="p-3 bg-violet-100 text-violet-900 rounded-lg ml-auto max-w-md">{entry['user']}</div>
          <div class="p-3 bg-gray-200 text-gray-900 rounded-lg mr-auto max-w-md mt-2">{entry['bot']}</div>
        </div>
        """
    
    content = f"""
    <div class="bg-white p-6 rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4">AI Insights</h2>
      <p class="mb-4 text-gray-600">Ask me anything about your dashboard or teaching needs! Type 'reset' to clear the chat.</p>
      <div class="max-h-96 overflow-y-auto mb-4 p-4 bg-gray-50 rounded">
        {chat_html if chat_html else '<p class="text-gray-500">Start chatting with me!</p>'}
      </div>
      <form method="post" class="flex space-x-2">
        <input type="text" name="message" placeholder="Ask the AI..." class="flex-1 p-2 border rounded focus:ring-2 focus:ring-violet-500" required>
        <button type="submit" class="bg-violet-600 text-white px-4 py-2 rounded hover:bg-violet-700 transition-colors">Send</button>
      </form>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='ai-insights', dark_mode=False)
# Authentication Endpoints
# -------------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        avatar = request.form.get('avatar')
        if not all([name, email, password]):
            flash("All fields are required.")
            return redirect(url_for('register'))
        users_ref = db.collection("users")
        existing = list(users_ref.where(filter=firestore.FieldFilter("email", "==", email)).stream())
        if existing:
            flash("User with that email already exists.")
            return redirect(url_for('register'))
        user_data = {
            "name": name,
            "email": email,
            "password": generate_password_hash(password),
            "avatar": avatar if avatar else "https://via.placeholder.com/40",
            "created_at": datetime.utcnow()
        }
        doc_ref = users_ref.add(user_data)
        flash("Registration successful! Please log in.")
        return redirect(url_for('login'))
    login_url = url_for('login')
    content = f"""
    <div class="max-w-md mx-auto p-6 bg-white rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4 text-center">Register</h2>
      <form method="post">
        <div class="mb-4">
          <label class="block mb-2">Name</label>
          <input type="text" name="name" class="w-full p-2 border rounded" placeholder="Your Name" required>
        </div>
        <div class="mb-4">
          <label class="block mb-2">Email</label>
          <input type="email" name="email" class="w-full p-2 border rounded" placeholder="you@example.com" required>
        </div>
        <div class="mb-4">
          <label class="block mb-2">Password</label>
          <input type="password" name="password" class="w-full p-2 border rounded" placeholder="********" required>
        </div>
        <div class="mb-4">
          <label class="block mb-2">Avatar URL (optional)</label>
          <input type="text" name="avatar" class="w-full p-2 border rounded" placeholder="https://">
        </div>
        <button type="submit" class="w-full bg-violet-600 text-white p-2 rounded hover:bg-violet-700 transition-colors">Register</button>
      </form>
      <p class="mt-4 text-center">Already have an account? <a href="{login_url}" class="text-violet-600 underline">Login</a></p>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='Register', dark_mode=False)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        if not all([email, password]):
            flash("Email and password are required.")
            return redirect(url_for('login'))
        users_ref = db.collection("users")
        results = list(users_ref.where(filter=firestore.FieldFilter("email", "==", email)).stream())
        if not results:
            flash("Invalid credentials.")
            return redirect(url_for('login'))
        user_doc = results[0]
        user = user_doc.to_dict()
        if not check_password_hash(user['password'], password):
            flash("Invalid credentials.")
            return redirect(url_for('login'))
        session['user'] = {'id': user_doc.id, 'name': user['name'], 'avatar': user['avatar'], 'email': user['email']}
        flash("Logged in successfully!")
        return redirect(url_for('dashboard'))
    register_url = url_for('register')
    content = f"""
    <div class="max-w-md mx-auto p-6 bg-white rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4 text-center">Login</h2>
      <form method="post">
        <div class="mb-4">
          <label class="block mb-2">Email</label>
          <input type="email" name="email" class="w-full p-2 border rounded" placeholder="you@example.com" required>
        </div>
        <div class="mb-4">
          <label class="block mb-2">Password</label>
          <input type="password" name="password" class="w-full p-2 border rounded" placeholder="********" required>
        </div>
        <button type="submit" class="w-full bg-violet-600 text-white p-2 rounded hover:bg-violet-700 transition-colors">Login</button>
      </form>
      <p class="mt-4 text-center">Don't have an account? <a href="{register_url}" class="text-violet-600 underline">Register</a></p>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='Login', dark_mode=False)

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash("Logged out successfully!")
    return redirect(url_for('login'))

# -------------------------------
# User Profile Endpoint
# -------------------------------
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = session.get('user')
    if request.method == 'POST':
        name = request.form.get('name')
        avatar = request.form.get('avatar')
        if name:
            user['name'] = name
        if avatar:
            user['avatar'] = avatar
        db.collection("users").document(user['id']).update({
            "name": user['name'],
            "avatar": user['avatar']
        })
        session['user'] = {'id': user['id'], 'name': user['name'], 'avatar': user['avatar'], 'email': user['email']}
        flash("Profile updated!")
        return redirect(url_for('profile'))
    content = f"""
    <div class="max-w-md mx-auto p-6 bg-white rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4 text-center">Your Profile</h2>
      <form method="post">
        <div class="mb-4">
          <img src="{user.get('avatar')}" alt="Avatar" class="w-20 h-20 rounded-full mx-auto mb-4">
          <label class="block mb-2">Name</label>
          <input type="text" name="name" value="{user.get('name')}" class="w-full p-2 border rounded" required>
        </div>
        <div class="mb-4">
          <label class="block mb-2">Avatar URL</label>
          <input type="text" name="avatar" value="{user.get('avatar')}" class="w-full p-2 border rounded">
        </div>
        <button type="submit" class="w-full bg-violet-600 text-white p-2 rounded hover:bg-violet-700 transition-colors">Update Profile</button>
      </form>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='Profile', dark_mode=False)

# -------------------------------
# Dashboard Endpoint
# -------------------------------
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    # Today's Schedule
    sched_ref = db.collection("schedule").document("today")
    doc = sched_ref.get()
    sched_data = doc.to_dict() if doc.exists else {s: "" for s in ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']}
    num_activities = sum(1 for act in sched_data.values() if act.strip())
    
    # Pending Tasks
    pending_tasks_query = db.collection("tasks").where("status", "==", "pending")
    pending_tasks_count = len(list(pending_tasks_query.stream()))
    
    # Student Alerts
    students_ref = db.collection("students").stream()
    alert_count = 0
    for doc in students_ref:
        student = doc.to_dict()
        sid = doc.id
        student_class = student.get("class")
        if not student_class:
            continue
        att_docs = [doc for doc in db.collection("attendance").stream() if doc.id.endswith(f"_{student_class}")]
        total = len(att_docs)
        if total == 0:
            continue
        present = sum(1 for doc in att_docs if doc.to_dict().get(sid, False))
        percentage = (present / total) * 100
        if percentage < 50:
            alert_count += 1
    
    # Upcoming Deadlines
    current_date = date.today().isoformat()
    future_date = (date.today() + timedelta(days=7)).isoformat()
    upcoming_deadlines_query = db.collection("tasks").where("deadline", ">=", current_date).where("deadline", "<=", future_date)
    upcoming_deadlines_count = len(list(upcoming_deadlines_query.stream()))
    
    content_template = """
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
      <a href="{{ url_for('today_schedule') }}" class="block p-4 bg-blue-100 text-blue-900 text-center rounded hover:bg-blue-200 transition-colors">
        <div class="text-lg">Today’s Schedule</div>
        <div class="text-sm">{{ num_activities }} activities</div>
      </a>
      <a href="{{ url_for('pending_tasks') }}" class="block p-4 bg-green-100 text-green-900 text-center rounded hover:bg-green-200 transition-colors">
        <div class="text-lg">Pending Tasks</div>
        <div class="text-sm">{{ pending_tasks_count }} tasks</div>
      </a>
      <a href="{{ url_for('student_alerts') }}" class="block p-4 bg-red-100 text-red-900 text-center rounded hover:bg-red-200 transition-colors">
        <div class="text-lg">Student Alerts</div>
        <div class="text-sm">{{ alert_count }} alerts</div>
      </a>
      <a href="{{ url_for('upcoming_deadlines') }}" class="block p-4 bg-yellow-100 text-yellow-900 text-center rounded hover:bg-yellow-200 transition-colors">
        <div class="text-lg">Upcoming Deadlines</div>
        <div class="text-sm">{{ upcoming_deadlines_count }} deadlines</div>
      </a>
    </div>
    """
    content = render_template_string(content_template, num_activities=num_activities, pending_tasks_count=pending_tasks_count, alert_count=alert_count, upcoming_deadlines_count=upcoming_deadlines_count)
    return render_template_string(base_template, content=content, active_page='dashboard', dark_mode=False)

# -------------------------------
# Attendance Endpoint (with Dropdown for Class Selection)
# -------------------------------
@app.route('/attendance', methods=['GET', 'POST'])
@login_required
def attendance():
    try:
        classes = ['CSE1', 'CSE2', 'CSE3', 'IS', 'AIML']
        selected_class = request.args.get('class_name', 'CSE1')
        date_str = request.args.get('date', date.today().strftime("%Y-%m-%d"))
        doc_id = f"{date_str}_{selected_class}"
        
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'update':
                student_id = request.form.get('student_id')
                status = request.form.get('status') == 'present'
                att_ref = db.collection("attendance").document(doc_id)
                att_doc = att_ref.get()
                att_data = att_doc.to_dict() if att_doc.exists else {}
                att_data[student_id] = status
                att_ref.set(att_data)
                flash("Attendance updated!")
            elif action == 'save':
                att_data = {sid: request.form.get(sid, 'absent') == 'present' for sid in request.form if sid not in ['action', 'date', 'class_name']}
                db.collection("attendance").document(doc_id).set(att_data)
                flash("Attendance saved!")
            return redirect(url_for('attendance', date=date_str, class_name=selected_class))

        att_ref = db.collection("attendance").document(doc_id)
        att_doc = att_ref.get()
        att_data = att_doc.to_dict() if att_doc.exists else {}

        students_ref = db.collection("students").where(filter=firestore.FieldFilter("class", "==", selected_class)).stream()
        students = [{"id": doc.id, **doc.to_dict()} for doc in students_ref]
        if not students:
            students = [{"id": f"{selected_class}_{i:02d}", "name": f"Student {i:02d}", "class": selected_class} for i in range(1, 31)]
            for student in students:
                db.collection("students").document(student["id"]).set(student)

        rows = ""
        for student in students:
            sid = student['id']
            status = "Present" if att_data.get(sid, False) else "Absent"
            checked_present = 'checked' if att_data.get(sid, False) else ''
            checked_absent = 'checked' if not att_data.get(sid, False) else ''
            rows += f"""
            <tr>
              <td class="p-4 border-b">{student.get('name')}</td>
              <td class="p-4 border-b">{status}</td>
              <td class="p-4 border-b">
                <label class="mr-4">
                  <input type="radio" name="{sid}" value="present" {checked_present} required> Present
                </label>
                <label>
                  <input type="radio" name="{sid}" value="absent" {checked_absent}> Absent
                </label>
              </td>
              <td class="p-4 border-b">
                <form method="post" action="{url_for('attendance')}" style="display:inline;">
                  <input type="hidden" name="student_id" value="{sid}">
                  <input type="hidden" name="status" value="present">
                  <input type="hidden" name="action" value="update">
                  <input type="hidden" name="date" value="{date_str}">
                  <input type="hidden" name="class_name" value="{selected_class}">
                  <button type="submit" class="border px-2 py-1 bg-green-500 text-white hover:bg-green-600 transition-colors">Present</button>
                </form>
                <form method="post" action="{url_for('attendance')}" style="display:inline;">
                  <input type="hidden" name="student_id" value="{sid}">
                  <input type="hidden" name="status" value="absent">
                  <input type="hidden" name="action" value="update">
                  <input type="hidden" name="date" value="{date_str}">
                  <input type="hidden" name="class_name" value="{selected_class}">
                  <button type="submit" class="border px-2 py-1 bg-red-500 text-white hover:bg-red-600 transition-colors">Absent</button>
                </form>
              </td>
            </tr>
            """
        class_options = "".join([f'<option value="{c}" {"selected" if c == selected_class else ""}>{c}</option>' for c in classes])
        content = f"""
        <div>
          <form method="get" action="{url_for('attendance')}" class="mb-4 flex flex-wrap gap-2">
            <label for="class_name" class="mr-2 font-medium">Select Class:</label>
            <select id="class_name" name="class_name" class="border p-2 rounded">
              {class_options}
            </select>
            <input type="date" name="date" value="{date_str}" class="border p-2 ml-2 rounded">
            <button type="submit" class="border p-2 ml-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">Go</button>
          </form>
          <form method="post" action="{url_for('attendance')}">
            <input type="hidden" name="action" value="save">
            <input type="hidden" name="date" value="{date_str}">
            <input type="hidden" name="class_name" value="{selected_class}">
            <table class="w-full border-collapse bg-white shadow-md rounded-lg">
              <thead>
                <tr class="bg-gray-200">
                  <th class="p-4 text-left border-b">Student Name</th>
                  <th class="p-4 text-left border-b">Current Status</th>
                  <th class="p-4 text-left border-b">Mark Attendance (Batch)</th>
                  <th class="p-4 text-left border-b">Quick Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows}
              </tbody>
            </table>
            <button type="submit" class="mt-4 border p-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">Save All</button>
          </form>
        </div>
        """
        return render_template_string(base_template, content=content, active_page='attendance', dark_mode=False)
    except Exception as e:
        flash(f"An error occurred: {str(e)}")
        return redirect(url_for('dashboard'))

# -------------------------------
# Today’s Schedule Endpoint
# -------------------------------
@app.route('/today-schedule', methods=['GET', 'POST'])
@login_required
def today_schedule():
    try:
        sched_ref = db.collection("schedule").document("today")
        if request.method == 'POST':
            sched_data = {slot: request.form.get(slot, '') for slot in ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']}
            sched_ref.set(sched_data)
            flash("Schedule saved!")
            return redirect(url_for('today_schedule'))
        doc = sched_ref.get()
        sched_data = doc.to_dict() if doc.exists else {s: "" for s in ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']}
        rows = "".join([f"""
        <tr>
          <td class="p-4 border-b">{slot}</td>
          <td class="p-4 border-b">
            <input type="text" name="{slot}" value="{act}" class="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">
          </td>
        </tr>
        """ for slot, act in sched_data.items()])
        content = f"""
        <div class="bg-white p-6 rounded-lg shadow-md">
          <h2 class="text-2xl font-bold mb-4">Today's Schedule</h2>
          <form method="post" action="{url_for('today_schedule')}">
            <table class="w-full border-collapse">
              <thead>
                <tr class="bg-gray-200">
                  <th class="p-4 text-left border-b">Time</th>
                  <th class="p-4 text-left border-b">Activity</th>
                </tr>
              </thead>
              <tbody>
                {rows}
              </tbody>
            </table>
            <div class="mt-4">
              <button type="submit" class="border p-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">Save Schedule</button>
            </div>
          </form>
        </div>
        """
        return render_template_string(base_template, content=content, active_page='today-schedule', dark_mode=False)
    except Exception as e:
        flash(f"An error occurred: {str(e)}")
        return redirect(url_for('dashboard'))

# -------------------------------
# Pending Tasks Endpoint (with Upcoming Deadlines Visualization)
# -------------------------------
@app.route('/pending-tasks', methods=['GET', 'POST'])
@login_required
def pending_tasks():
    tasks_ref = db.collection("tasks")
    groups_ref = db.collection("task_groups")
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_task':
            task_data = {
                "name": request.form.get('task_name'),
                "note": request.form.get('task_note'),
                "deadline": request.form.get('task_deadline') or None,
                "status": "pending",
                "groupId": request.form.get('task_group') or None,
                "highPriority": request.form.get('high_priority') == 'on',
                "pinned": request.form.get('pinned') == 'on',
                "tags": request.form.get('task_tags', '').split(',') if request.form.get('task_tags') else [],
                "checklist": request.form.get('task_checklist', '').split(',') if request.form.get('task_checklist') else [],
                "repeat": request.form.get('task_repeat') or None,
                "notificationsEnabled": request.form.get('notifications_enabled') == 'on',
                "createdAt": datetime.utcnow()
            }
            file = request.files.get('task_image')
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                unique_filename = f"{uuid.uuid4().hex}.{ext}"
                blob = bucket.blob(f"task_images/{unique_filename}")
                blob.upload_from_file(file)
                task_data["imageUrl"] = blob.public_url
            else:
                task_data["imageUrl"] = None
            tasks_ref.add(task_data)
            flash("Task added!")
        elif action == 'edit_task':
            task_id = request.form.get('task_id')
            task_ref = tasks_ref.document(task_id)
            task_data = task_ref.get().to_dict()
            updated_data = {
                "name": request.form.get('task_name'),
                "note": request.form.get('task_note'),
                "deadline": request.form.get('task_deadline') or None,
                "groupId": request.form.get('task_group') or None,
                "highPriority": request.form.get('high_priority') == 'on',
                "pinned": request.form.get('pinned') == 'on',
                "tags": request.form.get('task_tags', '').split(',') if request.form.get('task_tags') else [],
                "checklist": request.form.get('task_checklist', '').split(',') if request.form.get('task_checklist') else [],
                "repeat": request.form.get('task_repeat') or None,
                "notificationsEnabled": request.form.get('notifications_enabled') == 'on'
            }
            file = request.files.get('task_image')
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                unique_filename = f"{uuid.uuid4().hex}.{ext}"
                blob = bucket.blob(f"task_images/{unique_filename}")
                blob.upload_from_file(file)
                updated_data["imageUrl"] = blob.public_url
            else:
                updated_data["imageUrl"] = task_data.get("imageUrl")
            task_ref.update(updated_data)
            flash("Task updated!")
        elif action == 'delete_task':
            task_id = request.form.get('task_id')
            tasks_ref.document(task_id).delete()
            flash("Task deleted!")
        elif action == 'toggle_status':
            task_id = request.form.get('task_id')
            task_ref = tasks_ref.document(task_id)
            task_data = task_ref.get().to_dict()
            new_status = 'completed' if task_data.get('status') == 'pending' else 'pending'
            task_ref.update({"status": new_status})
            flash("Task status toggled!")
        elif action == 'cancel_task':
            task_id = request.form.get('task_id')
            tasks_ref.document(task_id).update({"status": "canceled"})
            flash("Task canceled!")
        elif action == 'add_group':
            group_name = request.form.get('group_name')
            if group_name:
                groups_ref.add({"name": group_name})
                flash("Group added!")
        elif action == 'delete_group':
            group_id = request.form.get('group_id')
            groups_ref.document(group_id).delete()
            for task in tasks_ref.where(filter=firestore.FieldFilter("groupId", "==", group_id)).stream():
                tasks_ref.document(task.id).update({"groupId": None})
            flash("Group deleted!")
        return redirect(url_for('pending_tasks', edit=request.form.get('edit_task_id')))

    tasks = [{"id": doc.id, **doc.to_dict()} for doc in tasks_ref.stream()]
    groups = [{"id": doc.id, **doc.to_dict()} for doc in groups_ref.stream()]
    search_query = request.args.get('search', '')
    if search_query:
        tasks = [task for task in tasks if search_query.lower() in task.get('name', '').lower()]
    
    edit_task_id = request.args.get('edit')
    editing_task = None
    if edit_task_id:
        editing_task = tasks_ref.document(edit_task_id).get().to_dict()
        editing_task["id"] = edit_task_id

    groups_html = "".join([f"""
    <li class="flex items-center justify-between p-2 bg-gray-100 rounded hover:bg-gray-200 transition-colors">
      <span>{group['name']}</span>
      <div class="flex space-x-2">
        <form method="post" action="{url_for('pending_tasks')}" style="display:inline;">
          <input type="hidden" name="action" value="delete_group">
          <input type="hidden" name="group_id" value="{group['id']}">
          <button type="submit" class="text-red-500 hover:text-red-700">Delete</button>
        </form>
      </div>
    </li>
    """ for group in groups])

    tasks_html = "".join([f"""
    <li class="flex items-center justify-between p-2 bg-gray-50 rounded hover:bg-gray-100 transition-colors">
      <div class="flex items-center space-x-2">
        <form id="toggle_form_{task['id']}" method="post" action="{url_for('pending_tasks')}">
          <input type="hidden" name="action" value="toggle_status">
          <input type="hidden" name="task_id" value="{task['id']}">
          <input type="checkbox" {'checked' if task['status'] == 'completed' else ''} onclick="toggleTaskStatus('{task['id']}')" class="h-4 w-4">
        </form>
        <span class="{'line-through text-gray-500' if task['status'] == 'completed' else ''}">{task['name']}</span>
        {f'<span class="text-sm text-gray-500">({[g["name"] for g in groups if g["id"] == task["groupId"]][0]})</span>' if task.get('groupId') and any(g['id'] == task['groupId'] for g in groups) else ''}
        {f'<img src="{task["imageUrl"]}" alt="{task["name"]} image" class="h-8 w-8 rounded-full ml-2">' if task.get('imageUrl') else ''}
      </div>
      <div class="flex space-x-2">
        <a href="{url_for('pending_tasks', edit=task['id'])}" class="text-blue-500 hover:underline">Edit</a>
        <form method="post" action="{url_for('pending_tasks')}" style="display:inline;">
          <input type="hidden" name="action" value="delete_task">
          <input type="hidden" name="task_id" value="{task['id']}">
          <button type="submit" class="text-red-500 hover:text-red-700">Delete</button>
        </form>
        <form method="post" action="{url_for('pending_tasks')}" style="display:inline;">
          <input type="hidden" name="action" value="cancel_task">
          <input type="hidden" name="task_id" value="{task['id']}">
          <button type="submit" class="text-gray-500 hover:text-gray-700">Cancel</button>
        </form>
      </div>
    </li>
    """ for task in tasks])

    upcoming_deadlines_cards = "".join([
        f"""
        <div class="p-4 bg-white border rounded shadow hover:shadow-lg transition-all duration-300">
          <h4 class="text-lg font-semibold">{task.get("name")}</h4>
          <p class="text-sm text-gray-600">Deadline: {task.get("deadline", "N/A")}</p>
          <p class="text-sm text-gray-500">{task.get("note", "")}</p>
        </div>
        """ for task in tasks if task.get("deadline")
    ])

    content = f"""
    <div class="flex flex-col min-h-screen bg-gray-100">
      <div class="p-4 bg-white shadow-md">
        <div class="flex items-center justify-between">
          <div class="flex space-x-2">
            <button class="border p-2 rounded hover:bg-gray-200 transition-colors" onclick="alert('Review functionality coming soon!')">Home</button>
            <button class="border p-2 rounded hover:bg-gray-200 transition-colors" onclick="alert('Focus functionality coming soon!')">Star</button>
            <button class="border p-2 rounded hover:bg-gray-200 transition-colors" onclick="alert('Notifications functionality coming soon!')">Bell</button>
          </div>
          <form method="get" action="{url_for('pending_tasks')}" class="flex space-x-2">
            <input type="text" name="search" value="{search_query}" placeholder="Search tasks" class="mt-1 p-2 border rounded focus:ring-2 focus:ring-blue-500">
            <button type="submit" class="border p-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">Search</button>
          </form>
        </div>
      </div>
      <div class="flex-1 flex">
        <div class="w-1/4 p-4 border-r border-gray-200 bg-white">
          <h2 class="text-lg font-semibold mb-2">Groups</h2>
          <ul class="space-y-2">
            {groups_html}
          </ul>
          <div class="mt-4">
            <form method="post" action="{url_for('pending_tasks')}">
              <input type="hidden" name="action" value="add_group">
              <input type="text" name="group_name" placeholder="New Group" class="mt-1 w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">
              <button type="submit" class="mt-2 border p-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">Add Group</button>
            </form>
          </div>
          <h2 class="text-lg font-semibold mt-6 mb-2">Tasks</h2>
          <ul class="space-y-2">
            {tasks_html}
          </ul>
        </div>
        <div class="w-3/4 p-4 bg-white">
          <h2 class="text-lg font-semibold mb-2">Task Editor</h2>
          <div>
            <h3 class="text-xl font-bold mb-2">Upcoming Deadlines</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              {upcoming_deadlines_cards}
            </div>
          </div>
          <form method="post" action="{url_for('pending_tasks')}" enctype="multipart/form-data" class="space-y-4 mt-6">
            <input type="hidden" name="action" value="{'edit_task' if editing_task else 'add_task'}">
            <input type="hidden" name="task_id" value="{editing_task['id'] if editing_task else ''}">
            <div>
              <label for="task_name" class="block text-sm font-medium text-gray-700">Task Name</label>
              <input type="text" id="task_name" name="task_name" value="{editing_task['name'] if editing_task else ''}" class="mt-1 w-full p-2 border rounded focus:ring-2 focus:ring-blue-500" required>
            </div>
            <div>
              <label for="task_note" class="block text-sm font-medium text-gray-700">Note</label>
              <textarea id="task_note" name="task_note" class="mt-1 w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">{editing_task['note'] if editing_task else ''}</textarea>
            </div>
            <div>
              <label for="task_deadline" class="block text-sm font-medium text-gray-700">Deadline</label>
              <input type="date" id="task_deadline" name="task_deadline" value="{editing_task['deadline'] if editing_task and editing_task.get('deadline') else ''}" class="mt-1 w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">
            </div>
            <div>
              <label for="task_group" class="block text-sm font-medium text-gray-700">Group</label>
              <select id="task_group" name="task_group" class="mt-1 w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">
                <option value="">No Group</option>
                {"".join([f'<option value="{g["id"]}" {"selected" if editing_task and editing_task.get("groupId") == g["id"] else ""}>{g["name"]}</option>' for g in groups])}
              </select>
            </div>
            <div>
              <label for="task_image" class="block text-sm font-medium text-gray-700">Image</label>
              <input type="file" id="task_image" name="task_image" accept="image/*" class="mt-1 w-full p-2 border rounded">
              {f'<img src="{editing_task["imageUrl"]}" alt="Task image" class="mt-2 h-20 w-20 rounded-full">' if editing_task and editing_task.get("imageUrl") else ''}
            </div>
            <div>
              <label class="inline-flex items-center">
                <input type="checkbox" name="high_priority" {'checked' if editing_task and editing_task.get("highPriority") else ''} class="h-4 w-4">
                <span class="ml-2">High Priority</span>
              </label>
            </div>
            <div>
              <label class="inline-flex items-center">
                <input type="checkbox" name="pinned" {'checked' if editing_task and editing_task.get("pinned") else ''} class="h-4 w-4">
                <span class="ml-2">Pinned</span>
              </label>
            </div>
            <div>
              <label for="task_tags" class="block text-sm font-medium text-gray-700">Tags (comma-separated)</label>
              <input type="text" id="task_tags" name="task_tags" value="{','.join(editing_task.get('tags', [])) if editing_task else ''}" class="mt-1 w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">
            </div>
            <div>
              <label for="task_checklist" class="block text-sm font-medium text-gray-700">Checklist (comma-separated)</label>
              <input type="text" id="task_checklist" name="task_checklist" value="{','.join(editing_task.get('checklist', [])) if editing_task else ''}" class="mt-1 w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">
            </div>
            <div>
              <label for="task_repeat" class="block text-sm font-medium text-gray-700">Repeat</label>
              <select id="task_repeat" name="task_repeat" class="mt-1 w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">
                <option value="">None</option>
                <option value="daily" {'selected' if editing_task and editing_task.get("repeat") == "daily" else ''}>Daily</option>
                <option value="weekly" {'selected' if editing_task and editing_task.get("repeat") == "weekly" else ''}>Weekly</option>
              </select>
            </div>
            <div>
              <label class="inline-flex items-center">
                <input type="checkbox" name="notifications_enabled" {'checked' if editing_task and editing_task.get("notificationsEnabled") else ''} class="h-4 w-4">
                <span class="ml-2">Notifications Enabled</span>
              </label>
            </div>
            <button type="submit" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">{'Save Task' if editing_task else 'Add Task'}</button>
          </form>
        </div>
      </div>
      <div class="p-4 border-t bg-white shadow-md">
        <div class="flex justify-end space-x-2">
          <button onclick="window.location.href='{url_for('pending_tasks')}'" class="border p-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors focus:outline focus:outline-2 focus:outline-green-500">
            <svg class="h-4 w-4 inline-block" fill="none" stroke="currentColor" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
            New Task
          </button>
        </div>
      </div>
    </div>
    <script>
      function toggleTaskStatus(taskId) {{
        document.getElementById('toggle_form_' + taskId).submit();
      }}
    </script>
    """
    return render_template_string(base_template, content=content, active_page='pending-tasks', dark_mode=False)

# -------------------------------
# Student Alerts Endpoint (Fixed Attendance Calculation)
# -------------------------------
@app.route('/student-alerts')
@login_required
def student_alerts():
    students_ref = db.collection("students").stream()
    alerts = []
    for doc in students_ref:
        student = doc.to_dict()
        sid = doc.id
        student_class = student.get("class")
        if not student_class:
            continue
        att_docs = [doc for doc in db.collection("attendance").stream() if doc.id.endswith(f"_{student_class}")]
        total = len(att_docs)
        if total == 0:
            continue
        present = sum(1 for doc in att_docs if doc.to_dict().get(sid, False))
        percentage = (present / total) * 100
        if percentage < 50:
            alerts.append({"name": student.get("name"), "percentage": percentage})
    alerts_html = "<ul class='space-y-2'>" + "".join([f"<li class='p-2 bg-red-100 rounded'><strong>{alert['name']}</strong> has less than 50% attendance ({alert['percentage']:.1f}%).</li>" for alert in alerts]) + "</ul>"
    content = f"""
    <div class="bg-white p-6 rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4">Student Alerts</h2>
      {alerts_html if alerts else '<p>No students with low attendance.</p>'}
    </div>
    """
    return render_template_string(base_template, content=content, active_page='student-alerts', dark_mode=False)

# -------------------------------
# Upcoming Deadlines Endpoint
# -------------------------------
@app.route('/upcoming-deadlines')
@login_required
def upcoming_deadlines():
    tasks_ref = db.collection("tasks").where(filter=firestore.FieldFilter("deadline", "!=", None)).order_by("deadline").stream()
    deadlines_cards = ""
    for doc in tasks_ref:
        task = doc.to_dict()
        deadline_str = task.get("deadline", "N/A")
        deadlines_cards += f"""
        <div class="p-4 bg-white border rounded shadow hover:shadow-lg transition-all duration-300">
          <h4 class="text-lg font-semibold">{task.get("name")}</h4>
          <p class="text-sm text-gray-600">Deadline: {deadline_str}</p>
          <p class="text-sm text-gray-500">{task.get("note", "")}</p>
        </div>
        """
    content = f"""
    <div class="bg-white p-6 rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4">Upcoming Deadlines</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        {deadlines_cards if deadlines_cards else '<p>No upcoming deadlines.</p>'}
      </div>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='upcoming-deadlines', dark_mode=False)

# -------------------------------
# Student Forum Endpoints
# -------------------------------
forum_template = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Student Forum</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="min-h-screen bg-gradient-to-b from-blue-100 to-white flex flex-col">
  <header class="bg-gradient-to-r from-blue-500 to-blue-700 text-white shadow-lg">
    <div class="container mx-auto px-4 py-6 flex justify-between items-center">
      <h1 class="text-3xl font-bold">Student Forum</h1>
      <a href="{{ url_for('dashboard') }}" class="text-white underline hover:text-gray-200 transition-colors">Back to Dashboard</a>
    </div>
  </header>
  <main class="flex-grow container mx-auto px-4 py-8 flex">
    <aside class="w-1/4 pr-4">
      <div class="mb-4 bg-white p-4 rounded-lg shadow-md">
        <h2 class="text-lg font-bold mb-2">Rooms</h2>
        <form method="post" action="{{ url_for('forum_add_room') }}">
          <div class="flex flex-col mb-2">
            <label for="newRoomName" class="block mb-2 text-sm font-medium text-gray-700">Room Name</label>
            <input type="text" id="newRoomName" name="newRoomName" placeholder="Enter room name" class="w-full p-3 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500" required>
          </div>
          <div class="flex flex-col mb-2">
            <label for="newRoomDescription" class="block mb-2 text-sm font-medium text-gray-700">Description</label>
            <textarea id="newRoomDescription" name="newRoomDescription" placeholder="Enter room description" class="w-full p-3 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500" required></textarea>
          </div>
          <button type="submit" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">Add Room</button>
        </form>
      </div>
      <div class="bg-white p-4 rounded-lg shadow-md">
        <h2 class="text-lg font-bold mb-2">Select a Room</h2>
        <div class="space-y-2">
          {% for room in rooms %}
            <a href="{{ url_for('student_forum', selected_room=room.id) }}" class="block w-full text-left px-4 py-2 border rounded {% if selected_room_id == room.id %}bg-blue-100 text-blue-600{% else %}text-gray-700 hover:bg-gray-100 transition-colors{% endif %}">
              {{ room.name }}
            </a>
          {% endfor %}
        </div>
      </div>
    </aside>
    <section class="w-3/4">
      {% if not selected_room_id %}
        <div class="text-center bg-white p-6 rounded-lg shadow-md">
          <h2 class="text-3xl font-bold mb-4">Welcome to the Student Forum</h2>
          <p class="text-gray-600">Please select a room to view posts or create a new room.</p>
        </div>
      {% else %}
        <div class="bg-white p-6 rounded-lg shadow-md">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-3xl font-bold">{{ rooms|selectattr('id', 'equalto', selected_room_id)|first.name }}</h2>
            <a href="{{ url_for('student_forum') }}" class="border px-4 py-2 rounded text-gray-700 hover:bg-gray-200 transition-colors">Back to Rooms</a>
          </div>
          <div class="mb-8 bg-gray-50 p-6 rounded-lg">
            <h3 class="text-2xl font-bold text-blue-600 mb-4">Create a Post</h3>
            <form method="post" action="{{ url_for('forum_add_post') }}">
              <input type="hidden" name="selected_room_id" value="{{ selected_room_id }}">
              <div class="mb-4">
                <label for="newPostTitle" class="block mb-2 text-sm font-medium text-gray-700">Title</label>
                <input type="text" id="newPostTitle" name="newPostTitle" placeholder="Enter post title" class="w-full p-3 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500" required>
              </div>
              <div class="mb-4">
                <label for="newPostContent" class="block mb-2 text-sm font-medium text-gray-700">Content</label>
                <textarea id="newPostContent" name="newPostContent" placeholder="Enter post content" class="w-full p-3 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500" required></textarea>
              </div>
              <button type="submit" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">Create Post</button>
            </form>
          </div>
          {% for post in posts %}
            {% if post.roomId == selected_room_id %}
              <div class="mb-8 bg-white shadow-lg rounded-lg p-6 relative">
                <div class="flex items-center">
                  <img src="https://github.com/nutlope.png" alt="Avatar" class="h-10 w-10 rounded-full">
                  <div class="ml-4">
                    <h4 class="text-lg font-bold text-blue-600">{{ post.title }}</h4>
                    <p class="text-gray-600">{{ post.content }}</p>
                  </div>
                </div>
                <div class="absolute top-2 right-2 flex space-x-2">
                  <form method="post" action="{{ url_for('forum_delete_post') }}" onsubmit="return confirm('Delete this post?');" style="display:inline;">
                    <input type="hidden" name="post_id" value="{{ post.id }}">
                    <button type="submit" class="text-red-500 hover:text-red-700">Delete</button>
                  </form>
                  <button class="text-gray-500 hover:text-gray-700" onclick="alert('Report functionality not implemented');">Report</button>
                </div>
                <div class="space-y-4 mt-4">
                  <form method="post" action="{{ url_for('forum_add_comment') }}">
                    <input type="hidden" name="post_id" value="{{ post.id }}">
                    <label for="comment-{{ post.id }}" class="block mb-2 text-sm font-medium text-gray-700">Add a Comment</label>
                    <textarea id="comment-{{ post.id }}" name="commentContent" placeholder="Enter your comment" class="w-full p-3 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500" required></textarea>
                    <button type="submit" class="mt-2 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">Submit Comment</button>
                  </form>
                  {% for comment in post.comments %}
                    <div class="mb-4">
                      <div class="bg-gray-100 p-4 rounded mb-2 relative">
                        <p class="text-gray-800">{{ comment.content }}</p>
                        <div class="absolute top-2 right-2 flex space-x-2">
                          <form method="post" action="{{ url_for('forum_toggle_star') }}" style="display:inline;">
                            <input type="hidden" name="post_id" value="{{ post.id }}">
                            <input type="hidden" name="comment_id" value="{{ comment.id }}">
                            <button type="submit" class="{% if comment.isStarred %}text-yellow-500 hover:text-yellow-700{% else %}text-gray-500 hover:text-gray-700{% endif %}">
                              {% if comment.isStarred %}Unstar{% else %}Star{% endif %}
                            </button>
                          </form>
                          <form method="post" action="{{ url_for('forum_delete_comment') }}" style="display:inline;" onsubmit="return confirm('Delete this comment?');">
                            <input type="hidden" name="post_id" value="{{ post.id }}">
                            <input type="hidden" name="comment_id" value="{{ comment.id }}">
                            <button type="submit" class="text-red-500 hover:text-red-700">Delete</button>
                          </form>
                          <button class="text-gray-500 hover:text-gray-700" onclick="alert('Report functionality not implemented');">Report</button>
                        </div>
                        <a href="{{ url_for('student_forum', selected_room=selected_room_id, active_comment=(comment.id if active_comment != comment.id else '')) }}" class="mt-2 text-sm text-blue-500 underline hover:text-blue-700 transition-colors">
                          {% if comment.replies|length > 0 and active_comment == comment.id %}Hide{% else %}Reply{% endif %}
                        </a>
                        {% if active_comment == comment.id %}
                          <div class="mt-2">
                            <form method="post" action="{{ url_for('forum_add_reply') }}">
                              <input type="hidden" name="post_id" value="{{ post.id }}">
                              <input type="hidden" name="comment_id" value="{{ comment.id }}">
                              <textarea name="replyContent" placeholder="Enter your reply" class="w-full p-3 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500" required></textarea>
                              <button type="submit" class="mt-2 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">Submit Reply</button>
                            </form>
                          </div>
                        {% endif %}
                        {% for reply in comment.replies %}
                          <div class="ml-4 mt-2 bg-gray-200 p-4 rounded relative">
                            <p class="text-gray-800">{{ reply.content }}</p>
                            <div class="absolute top-2 right-2 flex space-x-2">
                              <form method="post" action="{{ url_for('forum_toggle_star') }}" style="display:inline;">
                                <input type="hidden" name="post_id" value="{{ post.id }}">
                                <input type="hidden" name="comment_id" value="{{ reply.id }}">
                                <button type="submit" class="{% if reply.isStarred %}text-yellow-500 hover:text-yellow-700{% else %}text-gray-500 hover:text-gray-700{% endif %}">
                                  {% if reply.isStarred %}Unstar{% else %}Star{% endif %}
                                </button>
                              </form>
                              <form method="post" action="{{ url_for('forum_delete_comment') }}" style="display:inline;" onsubmit="return confirm('Delete this reply?');">
                                <input type="hidden" name="post_id" value="{{ post.id }}">
                                <input type="hidden" name="comment_id" value="{{ reply.id }}">
                                <button type="submit" class="text-red-500 hover:text-red-700">Delete</button>
                              </form>
                              <button class="text-gray-500 hover:text-gray-700" onclick="alert('Report functionality not implemented');">Report</button>
                            </div>
                          </div>
                        {% endfor %}
                      </div>
                    </div>
                  {% endfor %}
                </div>
              </div>
            {% endif %}
          {% endfor %}
        </div>
      {% endif %}
    </section>
  </main>
  <footer class="bg-gray-200 mt-8">
    <div class="container mx-auto px-4 py-6 text-center">
      <p class="text-gray-600">© 2023 Student Forum. All rights reserved.</p>
    </div>
  </footer>
</body>
</html>
"""

@app.route('/student-forum', methods=['GET'])
@login_required
def student_forum():
    selected_room_id = request.args.get('selected_room')
    active_comment = request.args.get('active_comment', type=int)
    rooms = [{"id": doc.id, **doc.to_dict()} for doc in db.collection("forum_rooms").stream()]
    posts = [{"id": doc.id, **doc.to_dict()} for doc in db.collection("forum_posts").stream()] if selected_room_id else []
    return render_template_string(forum_template, rooms=rooms, posts=posts, selected_room_id=selected_room_id, active_comment=active_comment)

@app.route('/forum/add-room', methods=['POST'])
@login_required
def forum_add_room():
    newRoomName = request.form.get('newRoomName')
    newRoomDescription = request.form.get('newRoomDescription')
    if newRoomName and newRoomDescription:
        db.collection("forum_rooms").add({"name": newRoomName, "description": newRoomDescription})
        flash("Room added!")
    else:
        flash("Room name and description are required.")
    return redirect(url_for('student_forum'))

@app.route('/forum/add-post', methods=['POST'])
@login_required
def forum_add_post():
    selected_room_id = request.form.get('selected_room_id')
    newPostTitle = request.form.get('newPostTitle')
    newPostContent = request.form.get('newPostContent')
    if selected_room_id and newPostTitle and newPostContent:
        post_data = {
            "roomId": selected_room_id,
            "title": newPostTitle,
            "content": newPostContent,
            "comments": [],
            "createdAt": datetime.utcnow()
        }
        db.collection("forum_posts").add(post_data)
        flash("Post created!")
    else:
        flash("Post title and content are required.")
    return redirect(url_for('student_forum', selected_room=selected_room_id))

@app.route('/forum/add-comment', methods=['POST'])
@login_required
def forum_add_comment():
    post_id = request.form.get('post_id')
    commentContent = request.form.get('commentContent')
    if post_id and commentContent:
        new_comment = {
            "id": int(time.time()*1000),
            "content": commentContent,
            "replies": [],
            "isAI": False,
            "isStarred": False
        }
        post_ref = db.collection("forum_posts").document(post_id)
        post_doc = post_ref.get()
        if post_doc.exists:
            data = post_doc.to_dict()
            comments = data.get("comments", [])
            comments.insert(0, new_comment)
            post_ref.update({"comments": comments})
            flash("Comment added!")
        else:
            flash("Post not found.")
        selected_room = post_doc.to_dict().get("roomId") if post_doc.exists else None
        return redirect(url_for('student_forum', selected_room=selected_room))
    flash("Comment content is required.")
    return redirect(url_for('student_forum'))

@app.route('/forum/add-reply', methods=['POST'])
@login_required
def forum_add_reply():
    post_id = request.form.get('post_id')
    comment_id = request.form.get('comment_id')
    replyContent = request.form.get('replyContent')
    if post_id and comment_id and replyContent:
        new_reply = {
            "id": int(time.time()*1000),
            "content": replyContent,
            "replies": [],
            "isAI": False,
            "isStarred": False
        }
        post_ref = db.collection("forum_posts").document(post_id)
        post_doc = post_ref.get()
        if post_doc.exists:
            data = post_doc.to_dict()
            comments = data.get("comments", [])
            for comment in comments:
                if str(comment.get("id")) == comment_id:
                    replies = comment.get("replies", [])
                    replies.insert(0, new_reply)
                    comment["replies"] = replies
                    break
            post_ref.update({"comments": comments})
            flash("Reply added!")
        else:
            flash("Post not found.")
        selected_room = post_doc.to_dict().get("roomId") if post_doc.exists else None
        return redirect(url_for('student_forum', selected_room=selected_room))
    flash("Reply content is required.")
    return redirect(url_for('student_forum'))

@app.route('/forum/delete-post', methods=['POST'])
@login_required
def forum_delete_post():
    post_id = request.form.get('post_id')
    if post_id:
        post_ref = db.collection("forum_posts").document(post_id)
        post_doc = post_ref.get()
        if post_doc.exists:
            db.collection("forum_posts").document(post_id).delete()
            flash("Post deleted!")
        else:
            flash("Post not found.")
        selected_room = post_doc.to_dict().get("roomId") if post_doc.exists else None
        return redirect(url_for('student_forum', selected_room=selected_room))
    flash("Post ID is required.")
    return redirect(url_for('student_forum'))

@app.route('/forum/delete-comment', methods=['POST'])
@login_required
def forum_delete_comment():
    post_id = request.form.get('post_id')
    comment_id = request.form.get('comment_id')
    if post_id and comment_id:
        post_ref = db.collection("forum_posts").document(post_id)
        post_doc = post_ref.get()
        if post_doc.exists:
            data = post_doc.to_dict()
            comments = data.get("comments", [])
            updated_comments = [c for c in comments if str(c.get("id")) != comment_id]
            for comment in comments:
                if "replies" in comment:
                    comment["replies"] = [r for r in comment.get("replies", []) if str(r.get("id")) != comment_id]
            post_ref.update({"comments": updated_comments if updated_comments else comments})
            flash("Comment/Reply deleted!")
        else:
            flash("Post not found.")
        selected_room = post_doc.to_dict().get("roomId") if post_doc.exists else None
        return redirect(url_for('student_forum', selected_room=selected_room))
    flash("Post ID and comment ID are required.")
    return redirect(url_for('student_forum'))

@app.route('/forum/toggle-star', methods=['POST'])
@login_required
def forum_toggle_star():
    post_id = request.form.get('post_id')
    comment_id = request.form.get('comment_id')
    if post_id and comment_id:
        post_ref = db.collection("forum_posts").document(post_id)
        post_doc = post_ref.get()
        if post_doc.exists:
            data = post_doc.to_dict()
            comments = data.get("comments", [])
            for comment in comments:
                if str(comment.get("id")) == comment_id:
                    comment["isStarred"] = not comment.get("isStarred", False)
                    break
                for reply in comment.get("replies", []):
                    if str(reply.get("id")) == comment_id:
                        reply["isStarred"] = not reply.get("isStarred", False)
                        break
            post_ref.update({"comments": comments})
            flash("Star toggled!")
        else:
            flash("Post not found.")
        selected_room = post_doc.to_dict().get("roomId") if post_doc.exists else None
        return redirect(url_for('student_forum', selected_room=selected_room))
    flash("Post ID and comment ID are required.")
    return redirect(url_for('student_forum'))

# -------------------------------
# Assignments and Tests Endpoints
# -------------------------------
@app.route('/assignments-tests', methods=['GET'])
@login_required
def assignments_tests():
    assignments = [{"id": doc.id, **doc.to_dict()} for doc in db.collection("assignments").order_by("deadline").stream()]
    tests = [{"id": doc.id, **doc.to_dict()} for doc in db.collection("tests").order_by("date").stream()]
    assignments_list = "".join([f"""
    <li class="p-2 bg-gray-50 rounded hover:bg-gray-100 transition-colors">{a['subject']} - Deadline: {a['deadline']} <a href="{a['file_url']}" target="_blank" class="text-blue-500 hover:underline">Download</a> <a href="{url_for('view_submissions', assignment_id=a['id'])}" class="text-blue-500 hover:underline ml-2">View Submissions</a></li>
    """ for a in assignments])
    tests_list = "".join([f"""
    <li class="p-2 bg-gray-50 rounded hover:bg-gray-100 transition-colors">{t['subject']} - Date: {t['date']} Time: {t['time']} <a href="{t['test_link']}" target="_blank" class="text-blue-500 hover:underline">Test Link</a> <a href="{url_for('view_test_results', test_id=t['id'])}" class="text-blue-500 hover:underline ml-2">View Results</a></li>
    """ for t in tests])
    content = f"""
    <div class="bg-white p-6 rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4">Assignments</h2>
      <a href="{url_for('add_assignment')}" class="border p-2 mb-4 inline-block bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">Add New Assignment</a>
      <ul class="mb-8 space-y-2">{assignments_list if assignments_list else '<p>No assignments.</p>'}</ul>
      <h2 class="text-2xl font-bold mb-4">Tests</h2>
      <a href="{url_for('add_test')}" class="border p-2 mb-4 inline-block bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">Add New Test</a>
      <ul class="space-y-2">{tests_list if tests_list else '<p>No tests.</p>'}</ul>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='assignments-tests', dark_mode=False)

@app.route('/add_assignment', methods=['GET', 'POST'])
@login_required
def add_assignment():
    if request.method == 'POST':
        subject = request.form.get('subject')
        deadline = request.form.get('deadline')
        file = request.files.get('file')
        if subject and deadline and file:
            ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
            unique_filename = f"{uuid.uuid4().hex}.{ext}"
            blob = bucket.blob(f"assignments/{unique_filename}")
            blob.upload_from_file(file)
            file_url = blob.public_url
            assignment_data = {
                "subject": subject,
                "deadline": deadline,
                "file_url": file_url,
                "created_at": datetime.utcnow()
            }
            db.collection("assignments").add(assignment_data)
            flash("Assignment added!")
            return redirect(url_for('assignments_tests'))
        flash("All fields are required.")
        return redirect(url_for('add_assignment'))
    content = """
    <div class="bg-white p-6 rounded-lg shadow-md max-w-md mx-auto">
      <h2 class="text-2xl font-bold mb-4">Add New Assignment</h2>
      <form method="post" enctype="multipart/form-data">
        <div class="mb-4">
          <label for="subject" class="block text-sm font-medium text-gray-700">Subject</label>
          <input type="text" id="subject" name="subject" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" required>
        </div>
        <div class="mb-4">
          <label for="deadline" class="block text-sm font-medium text-gray-700">Deadline</label>
          <input type="date" id="deadline" name="deadline" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" required>
        </div>
        <div class="mb-4">
          <label for="file" class="block text-sm font-medium text-gray-700">File</label>
          <input type="file" id="file" name="file" accept=".pdf,.txt" class="w-full p-3 border rounded" required>
        </div>
        <button type="submit" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">Add Assignment</button>
      </form>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='add_assignment', dark_mode=False)

@app.route('/assignment/<assignment_id>/submissions', methods=['GET'])
@login_required
def view_submissions(assignment_id):
    assignment_doc = db.collection("assignments").document(assignment_id).get()
    if not assignment_doc.exists:
        flash("Assignment not found.")
        return redirect(url_for('assignments_tests'))
    assignment = assignment_doc.to_dict()
    submissions = [{"id": doc.id, **doc.to_dict()} for doc in db.collection("assignments").document(assignment_id).collection("submissions").stream()]
    submissions_list = "".join([f"""
    <li class="p-2 bg-gray-50 rounded hover:bg-gray-100 transition-colors flex items-center justify-between">
      <span>{s['student_name']} - <a href="{s['file_url']}" target="_blank" class="text-blue-500 hover:underline">View File</a> - Grade: {s.get('grade', 'Not graded')}</span>
      <form method="post" action="{url_for('grade_submission', assignment_id=assignment_id, submission_id=s['id'])}" class="inline-flex items-center space-x-2">
        <input type="number" name="grade" min="0" max="100" value="{s.get('grade', '')}" class="border p-1 w-20 rounded focus:ring-2 focus:ring-blue-500" placeholder="Grade">
        <button type="submit" class="border p-1 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">Grade</button>
      </form>
    </li>
    """ for s in submissions])
    content = f"""
    <div class="bg-white p-6 rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4">Submissions for {assignment['subject']}</h2>
      <ul class="space-y-2">{submissions_list if submissions_list else '<p>No submissions.</p>'}</ul>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='submissions', dark_mode=False)

@app.route('/assignment/<assignment_id>/submission/<submission_id>/grade', methods=['POST'])
@login_required
def grade_submission(assignment_id, submission_id):
    grade = request.form.get('grade')
    if grade:
        try:
            grade_int = int(grade)
            if 0 <= grade_int <= 100:
                db.collection("assignments").document(assignment_id).collection("submissions").document(submission_id).update({"grade": grade_int})
                flash("Submission graded!")
            else:
                flash("Grade must be between 0 and 100.")
        except ValueError:
            flash("Invalid grade value.")
    else:
        flash("Grade is required.")
    return redirect(url_for('view_submissions', assignment_id=assignment_id))

@app.route('/add_test', methods=['GET', 'POST'])
@login_required
def add_test():
    if request.method == 'POST':
        subject = request.form.get('subject')
        date = request.form.get('date')
        time_val = request.form.get('time')
        max_marks = request.form.get('max_marks')
        duration = request.form.get('duration')
        test_link = request.form.get('test_link')
        if all([subject, date, time_val, max_marks, duration, test_link]):
            try:
                max_marks_int = int(max_marks)
                test_data = {
                    "subject": subject,
                    "date": date,
                    "time": time_val,
                    "max_marks": max_marks_int,
                    "duration": duration,
                    "test_link": test_link,
                    "created_at": datetime.utcnow()
                }
                db.collection("tests").add(test_data)
                flash("Test added!")
                return redirect(url_for('assignments_tests'))
            except ValueError:
                flash("Max marks must be a number.")
        flash("All fields are required.")
        return redirect(url_for('add_test'))
    content = """
    <div class="bg-white p-6 rounded-lg shadow-md max-w-md mx-auto">
      <h2 class="text-2xl font-bold mb-4">Add New Test</h2>
      <form method="post">
        <div class="mb-4">
          <label for="subject" class="block text-sm font-medium text-gray-700">Subject</label>
          <input type="text" id="subject" name="subject" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" required>
        </div>
        <div class="mb-4">
          <label for="date" class="block text-sm font-medium text-gray-700">Date</label>
          <input type="date" id="date" name="date" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" required>
        </div>
        <div class="mb-4">
          <label for="time" class="block text-sm font-medium text-gray-700">Time</label>
          <input type="time" id="time" name="time" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" required>
        </div>
        <div class="mb-4">
          <label for="max_marks" class="block text-sm font-medium text-gray-700">Max Marks</label>
          <input type="number" id="max_marks" name="max_marks" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" required min="1">
        </div>
        <div class="mb-4">
          <label for="duration" class="block text-sm font-medium text-gray-700">Duration</label>
          <input type="text" id="duration" name="duration" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" placeholder="e.g., 90 mins" required>
        </div>
        <div class="mb-4">
          <label for="test_link" class="block text-sm font-medium text-gray-700">Test Link</label>
          <input type="url" id="test_link" name="test_link" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" required>
        </div>
        <button type="submit" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">Add Test</button>
      </form>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='add_test', dark_mode=False)

@app.route('/test/<test_id>/results', methods=['GET'])
@login_required
def view_test_results(test_id):
    test_doc = db.collection("tests").document(test_id).get()
    if not test_doc.exists:
        flash("Test not found.")
        return redirect(url_for('assignments_tests'))
    test = test_doc.to_dict()
    results = {doc.id: doc.to_dict() for doc in db.collection("tests").document(test_id).collection("results").stream()}
    students = [{"id": doc.id, **doc.to_dict()} for doc in db.collection("students").stream()]
    rows = ""
    for student in students:
        sid = student['id']
        score = results.get(sid, {}).get('score', 'Not graded')
        rows += f"""
        <tr class="hover:bg-gray-100 transition-colors">
          <td class="p-4 border-b">{student.get('name')}</td>
          <td class="p-4 border-b">{score}</td>
          <td class="p-4 border-b">
            <form method="post" action="{url_for('enter_test_score', test_id=test_id, student_id=sid)}" class="flex items-center space-x-2">
              <input type="number" name="score" min="0" max="{test['max_marks']}" value="{score if score != 'Not graded' else ''}" class="border p-1 w-20 rounded focus:ring-2 focus:ring-blue-500" placeholder="Score">
              <button type="submit" class="border p-1 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">Enter Score</button>
            </form>
          </td>
        </tr>
        """
    content = f"""
    <div class="bg-white p-6 rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4">Results for {test['subject']} (Max Marks: {test['max_marks']})</h2>
      <table class="w-full border-collapse">
        <thead>
          <tr class="bg-gray-200">
            <th class="p-4 text-left border-b">Student Name</th>
            <th class="p-4 text-left border-b">Score</th>
            <th class="p-4 text-left border-b">Enter Score</th>
          </tr>
        </thead>
        <tbody>
          {rows if rows else '<tr><td colspan="3" class="p-4 text-center">No students found.</td></tr>'}
        </tbody>
      </table>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='test_results', dark_mode=False)

@app.route('/test/<test_id>/student/<student_id>/score', methods=['POST'])
@login_required
def enter_test_score(test_id, student_id):
    score = request.form.get('score')
    test_doc = db.collection("tests").document(test_id).get()
    if not test_doc.exists:
        flash("Test not found.")
        return redirect(url_for('assignments_tests'))
    test = test_doc.to_dict()
    if score:
        try:
            score_int = int(score)
            if 0 <= score_int <= test['max_marks']:
                student_doc = db.collection("students").document(student_id).get()
                if student_doc.exists:
                    student = student_doc.to_dict()
                    result_data = {
                        "student_id": student_id,
                        "student_name": student.get("name", "Unknown"),
                        "score": score_int,
                        "timestamp": datetime.datetime.utcnow()
                    }
                    db.collection("tests").document(test_id).collection("results").document(student_id).set(result_data)
                    flash("Score entered!")
                else:
                    flash("Student not found.")
            else:
                flash(f"Score must be between 0 and {test['max_marks']}.")
        except ValueError:
            flash("Invalid score value.")
    else:
        flash("Score is required.")
    return redirect(url_for('view_test_results', test_id=test_id))

# -------------------------------
# Student Performance Endpoint (Fixed Attendance Calculation)
# -------------------------------
@app.route('/student-performance')
@login_required
def student_performance():
    students = [{"id": doc.id, **doc.to_dict()} for doc in db.collection("students").stream()]
    students_list = []
    for student in students:
        sid = student["id"]
        student_class = student.get("class")
        if not student_class:
            continue
        att_docs = [doc for doc in db.collection("attendance").stream() if doc.id.endswith(f"_{student_class}")]
        total = len(att_docs)
        if total == 0:
            attendance_percentage = 0
        else:
            present = sum(1 for doc in att_docs if doc.to_dict().get(sid, False))
            attendance_percentage = (present / total) * 100
        students_list.append({"name": student.get("name"), "attendance_percentage": attendance_percentage})
    rows = "".join([f"""
    <tr class="hover:bg-gray-100 transition-colors">
      <td class="p-4 border-b">{student['name']}</td>
      <td class="p-4 border-b">{student['attendance_percentage']:.1f}%</td>
    </tr>
    """ for student in students_list])
    content = f"""
    <div class="bg-white p-6 rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4">Student Performance</h2>
      <table class="w-full border-collapse">
        <thead>
          <tr class="bg-gray-200">
            <th class="p-4 text-left border-b">Student Name</th>
            <th class="p-4 text-left border-b">Attendance Percentage</th>
          </tr>
        </thead>
        <tbody>
          {rows if rows else '<tr><td colspan="2" class="p-4 text-center">No students found.</td></tr>'}
        </tbody>
      </table>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='student-performance', dark_mode=False)

# -------------------------------
# Student Management Endpoints
# -------------------------------
@app.route('/students')
@login_required
def students():
    students = [{"id": doc.id, **doc.to_dict()} for doc in db.collection("students").stream()]
    rows = "".join([f"""
    <tr class="hover:bg-gray-100 transition-colors">
      <td class="p-4 border-b">{s['id']}</td>
      <td class="p-4 border-b">{s.get('name')}</td>
      <td class="p-4 border-b">{s.get('class', 'N/A')}</td>
      <td class="p-4 border-b flex space-x-2">
        <a href="{url_for('edit_student', student_id=s['id'])}" class="border px-2 py-1 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">Edit</a>
        <form method="post" action="{url_for('delete_student', student_id=s['id'])}" style="display:inline;" onsubmit="return confirm('Delete this student?');">
          <button type="submit" class="border px-2 py-1 bg-red-500 text-white rounded hover:bg-red-600 transition-colors">Delete</button>
        </form>
      </td>
    </tr>
    """ for s in students])
    content = f"""
    <div class="bg-white p-6 rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4">Student Management</h2>
      <a href="{url_for('add_student')}" class="border p-2 mb-4 inline-block bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">Add New Student</a>
      <table class="w-full border-collapse">
        <thead>
          <tr class="bg-gray-200">
            <th class="p-4 text-left border-b">Student ID</th>
            <th class="p-4 text-left border-b">Name</th>
            <th class="p-4 text-left border-b">Class</th>
            <th class="p-4 text-left border-b">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows if rows else '<tr><td colspan="4" class="p-4 text-center">No students found.</td></tr>'}
        </tbody>
      </table>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='students', dark_mode=False)

@app.route('/students/add', methods=['GET', 'POST'])
@login_required
def add_student():
    if request.method == 'POST':
        name = request.form.get('name')
        class_name = request.form.get('class')
        if name and class_name:
            student_data = {"name": name, "class": class_name}
            db.collection("students").add(student_data)
            flash("Student added!")
            return redirect(url_for('students'))
        flash("Name and class are required.")
        return redirect(url_for('add_student'))
    content = """
    <div class="bg-white p-6 rounded-lg shadow-md max-w-md mx-auto">
      <h2 class="text-2xl font-bold mb-4">Add New Student</h2>
      <form method="post">
        <div class="mb-4">
          <label for="name" class="block text-sm font-medium text-gray-700">Name</label>
          <input type="text" id="name" name="name" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" required>
        </div>
        <div class="mb-4">
          <label for="class" class="block text-sm font-medium text-gray-700">Class</label>
          <select id="class" name="class" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" required>
            <option value="CSE1">CSE1</option>
            <option value="CSE2">CSE2</option>
            <option value="CSE3">CSE3</option>
            <option value="IS">IS</option>
            <option value="AIML">AIML</option>
          </select>
        </div>
        <button type="submit" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">Add Student</button>
      </form>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='students', dark_mode=False)

@app.route('/students/edit/<student_id>', methods=['GET', 'POST'])
@login_required
def edit_student(student_id):
    student_ref = db.collection("students").document(student_id)
    student_doc = student_ref.get()
    if not student_doc.exists:
        flash("Student not found.")
        return redirect(url_for('students'))
    student = student_doc.to_dict()
    if request.method == 'POST':
        name = request.form.get('name')
        class_name = request.form.get('class')
        if name and class_name:
            student_ref.update({"name": name, "class": class_name})
            flash("Student updated!")
            return redirect(url_for('students'))
        flash("Name and class are required.")
        return redirect(url_for('edit_student', student_id=student_id))
    content = f"""
    <div class="bg-white p-6 rounded-lg shadow-md max-w-md mx-auto">
      <h2 class="text-2xl font-bold mb-4">Edit Student</h2>
      <form method="post">
        <div class="mb-4">
          <label for="name" class="block text-sm font-medium text-gray-700">Name</label>
          <input type="text" id="name" name="name" value="{student.get('name')}" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" required>
        </div>
        <div class="mb-4">
          <label for="class" class="block text-sm font-medium text-gray-700">Class</label>
          <select id="class" name="class" class="w-full p-3 border rounded focus:ring-2 focus:ring-blue-500" required>
            <option value="CSE1" {"selected" if student.get('class') == 'CSE1' else ""}>CSE1</option>
            <option value="CSE2" {"selected" if student.get('class') == 'CSE2' else ""}>CSE2</option>
            <option value="CSE3" {"selected" if student.get('class') == 'CSE3' else ""}>CSE3</option>
            <option value="IS" {"selected" if student.get('class') == 'IS' else ""}>IS</option>
            <option value="AIML" {"selected" if student.get('class') == 'AIML' else ""}>AIML</option>
          </select>
        </div>
        <button type="submit" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">Update Student</button>
      </form>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='students', dark_mode=False)

@app.route('/students/delete/<student_id>', methods=['POST'])
@login_required
def delete_student(student_id):
    student_ref = db.collection("students").document(student_id)
    if student_ref.get().exists:
        student_ref.delete()
        flash("Student deleted!")
    else:
        flash("Student not found.")
    return redirect(url_for('students'))

# -------------------------------
# Messaging Endpoint
# -------------------------------
@app.route('/messaging', methods=['GET', 'POST'])
@login_required
def messaging():
    current_user = session['user']['email']
    if request.method == 'POST':
        if request.form.get('action') == 'new_conversation':
            target = request.form.get('target')
            if not target:
                flash("Please enter a username or email to start a conversation.")
                return redirect(url_for('messaging'))
            # Check if target user exists
            target_user = list(db.collection("users").where(filter=firestore.FieldFilter("email", "==", target)).stream())
            if not target_user:
                flash("Target user does not exist.")
                return redirect(url_for('messaging'))
            conv_ref = db.collection("conversations")
            existing = None
            for conv in conv_ref.where(filter=firestore.FieldFilter("participants", "array_contains", current_user)).stream():
                data = conv.to_dict()
                if target in data.get("participants", []):
                    existing = conv
                    break
            if existing:
                conv_id = existing.id
            else:
                new_conv = {
                    "participants": [current_user, target],
                    "messages": []
                }
                conv_doc = conv_ref.add(new_conv)
                conv_id = conv_doc[1].id
            return redirect(url_for('messaging', conversation_id=conv_id))
        elif request.form.get('action') == 'send_message':
            conv_id = request.form.get('conversation_id')
            message_text = request.form.get('message')
            if conv_id and message_text:
                conv_ref = db.collection("conversations").document(conv_id)
                conv_doc = conv_ref.get()
                if conv_doc.exists:
                    conv = conv_doc.to_dict()
                    messages = conv.get("messages", [])
                    messages.append({
                        "sender": current_user,
                        "content": message_text,
                        "timestamp": datetime.utcnow()
                    })
                    conv_ref.update({"messages": messages})
                    flash("Message sent!")
                else:
                    flash("Conversation not found.")
            else:
                flash("Message content is required.")
            return redirect(url_for('messaging', conversation_id=conv_id))
    conv_id = request.args.get('conversation_id')
    if conv_id:
        conv_ref = db.collection("conversations").document(conv_id)
        conv_data = conv_ref.get().to_dict() or {}
        if not conv_data:
            flash("Conversation not found.")
            return redirect(url_for('messaging'))
        messages = conv_data.get("messages", [])
        other_participants = [p for p in conv_data.get("participants", []) if p != current_user]
        content = f"""
        <div class="bg-white p-6 rounded-lg shadow-md">
          <h2 class='text-xl font-bold mb-4'>Conversation with {", ".join(other_participants)}</h2>
          <div class="mb-4 max-h-96 overflow-y-auto p-4 bg-gray-50 rounded">
        """
        for msg in messages:
            sender = msg.get("sender")
            content_class = "bg-blue-100 text-blue-900" if sender == current_user else "bg-gray-200 text-gray-900"
            align_class = "ml-auto" if sender == current_user else "mr-auto"
            content += f"""
            <div class='p-2 my-1 border rounded {content_class} w-fit {align_class}'>
              <strong>{sender}:</strong> {msg.get("content")}
              <div class="text-xs text-gray-500">{msg.get("timestamp").strftime('%Y-%m-%d %H:%M:%S')}</div>
            </div>
            """
        content += """
          </div>
          <form method="post" class="mb-4">
            <input type="hidden" name="action" value="send_message">
            <input type="hidden" name="conversation_id" value="{conv_id}">
            <input type="text" name="message" placeholder="Type a message..." class="border p-2 w-full rounded focus:ring-2 focus:ring-blue-500" required>
            <button type="submit" class="mt-2 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">Send</button>
          </form>
          <a href="{url}" class="inline-block text-blue-500 hover:underline">Back to Conversations</a>
        </div>
        """.format(conv_id=conv_id, url=url_for('messaging'))
        return render_template_string(base_template, content=content, active_page='messaging', dark_mode=False)
    else:
        conv_ref = db.collection("conversations")
        user_convs = conv_ref.where(filter=firestore.FieldFilter("participants", "array_contains", current_user)).stream()
        content = "<div class='bg-white p-6 rounded-lg shadow-md'>"
        content += "<h2 class='text-xl font-bold mb-4'>Your Conversations</h2>"
        conv_list = ""
        for conv in user_convs:
            data = conv.to_dict()
            other = [p for p in data.get("participants", []) if p != current_user]
            conv_url = url_for('messaging', conversation_id=conv.id)
            conv_list += f"""
            <div class='p-2 border rounded mb-2 hover:bg-gray-100 transition-colors'>
              <a href='{conv_url}' class='text-blue-500 hover:underline'>{", ".join(other)}</a>
            </div>
            """
        content += conv_list if conv_list else "<p>No conversations yet.</p>"
        content += """
        <h3 class='text-lg font-bold mt-4'>Start New Conversation</h3>
        <form method="post">
          <input type="hidden" name="action" value="new_conversation">
          <input type="email" name="target" placeholder="Enter user email" class="border p-2 w-full rounded focus:ring-2 focus:ring-blue-500" required>
          <button type="submit" class="mt-2 bg-green-500 text-white px-4 py-2 rounded hover:bg-green-600 transition-colors">Start Chat</button>
        </form>
        </div>
        """
        return render_template_string(base_template, content=content, active_page='messaging', dark_mode=False)

# -------------------------------
# Settings Endpoint (Fixed Logout and Delete Account)
# -------------------------------
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        setting_type = request.form.get('setting_type')
        if setting_type == 'logout':
            return redirect(url_for('logout'))
        elif setting_type == 'delete_account':
            user_id = session['user']['id']
            db.collection("users").document(user_id).delete()
            session.pop('user', None)
            flash("Account deleted successfully!")
            return redirect(url_for('login'))
        else:
            flash("Settings updated!")
            return redirect(url_for('settings'))
    content = """
    <div class="bg-white p-6 rounded-lg shadow-md">
      <h2 class="text-2xl font-bold mb-4">Settings</h2>
      <div class="space-y-4">
        <div class="flex items-center justify-between p-4 bg-gray-50 rounded">
          <div class="flex items-center space-x-2">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>
            <span class="text-lg font-medium">Account</span>
          </div>
          <a href="#" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors" onclick="alert('Edit Account')">Edit</a>
        </div>
        <div class="flex items-center justify-between p-4 bg-gray-50 rounded">
          <div class="flex items-center space-x-2">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 12a4 4 0 10-8 0 4 4 0 008 0zm0 0v1.5a2.5 2.5 0 005 0V12a9 9 0 10-9 9m4.5-1.206a8.959 8.959 0 01-4.5 1.207"/></svg>
            <span class="text-lg font-medium">Email</span>
          </div>
          <a href="#" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors" onclick="alert('Change Email')">Change</a>
        </div>
        <div class="flex items-center justify-between p-4 bg-gray-50 rounded">
          <div class="flex items-center space-x-2">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-4.215A2.422 2.422 0 0118.5 11.5V8a2 2 0 00-2-2H8a2 2 0 00-2 2v3.5c0 .464-.184 .908-.512 1.285L4 17h5m6 0v-2a2 2 0 012-2h2a2 2 0 012 2v2m-6 0h6"/></svg>
            <span class="text-lg font-medium">Notifications</span>
          </div>
          <a href="#" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors" onclick="alert('Manage Notifications')">Manage</a>
        </div>
        <div class="flex items-center justify-between p-4 bg-gray-50 rounded">
          <div class="flex items-center space-x-2">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/></svg>
            <span class="text-lg font-medium">Security</span>
          </div>
          <a href="#" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors" onclick="alert('Security Settings')">Edit</a>
        </div>
        <div class="flex items-center justify-between p-4 bg-gray-50 rounded">
          <form method="post" class="w-full">
            <input type="hidden" name="setting_type" value="delete_account">
            <button type="submit" class="w-full bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600 transition-colors" onclick="return confirm('Are you sure you want to delete your account? This action cannot be undone.')">Delete Account</button>
          </form>
        </div>
        <div class="flex items-center justify-between p-4 bg-gray-50 rounded">
          <form method="post" class="w-full">
            <input type="hidden" name="setting_type" value="logout">
            <button type="submit" class="w-full bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600 transition-colors" onclick="return confirm('Are you sure you want to log out?')">Logout</button>
          </form>
        </div>
      </div>
    </div>
    """
    return render_template_string(base_template, content=content, active_page='settings', dark_mode=False)

# -------------------------------
# Run the Flask App
# -------------------------------
if __name__ == '__main__':
    app.run(debug=True,port=5001)
