from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, jsonify
# Ensure your static imports work relative to the root directory
from static.db.db import add, get_all, delete, delete_many
from email_service import send_email_wrapper
from datetime import datetime

app = Flask(__name__)

# --- Standard Routes ---
@app.route('/cancel-timings', methods=['POST'])
def cancel_timings():
    try:
        data = request.get_json()
        add('MEET', 'SCHEDULED_MEETS', data)
        return jsonify({'message': 'Timings cancelled successfully'})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/get-timings', methods=['GET'])
def get_timings():
    try:
        data = request.args.get('date')
        all_timings = get_all('MEET', 'TIMINGS', {})
        meets = get_all('MEET', 'SCHEDULED_MEETS', {"date": data})
        meet_timings = [meet['time_slot'] for meet in meets]
        # Check if all_timings has data before accessing index 0 to avoid crashes
        if not all_timings:
             return jsonify({'valid_timings': []})
             
        valid_timings = [timing for timing in all_timings[0]['time_slots'] if timing not in meet_timings]
        return jsonify({'valid_timings': valid_timings})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/get-meet-timings', methods=['GET'])
def get_meet_timings():
    try:
        data = request.args.get('date')
        meets = get_all('MEET', 'SCHEDULED_MEETS', {"date": data})
        meet_timings = [meet['time_slot'] for meet in meets]
        return jsonify({'valid_timings': meet_timings})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/remove-timings', methods=['POST'])
def remove_meeting():
    try:
        data = request.get_json()
        delete('MEET', 'SCHEDULED_MEETS', data)
        return jsonify({'message': 'Meeting removed successfully'})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/add-meeting', methods=['POST'])
def add_meeting():
    try:
        data = request.get_json()
        add('MEET', 'SCHEDULED_MEETS', data)
        return jsonify({'message': 'Meeting added successfully'})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/send-email', methods=['POST'])
def send_email():
    try:
        data = request.get_json()
        send_email_wrapper(data['to'], data['subject'], data['body'])
        return jsonify({'message': 'Email sent successfully'})
    except Exception as e:
        return jsonify({'error': str(e)})

# --- NEW: CRON JOB ROUTE ---
# Instead of background scheduler, Vercel will hit this URL
@app.route('/cron/delete-old-meetings', methods=['GET'])
def trigger_delete_old_meetings():
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        query = {"date": {"$lt": today}}
        delete_many('MEET', 'SCHEDULED_MEETS', query)
        return jsonify({"status": "success", "message": f"Deleted meetings before {today}"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})

@app.route('/')
def index():
    return render_template('index.html')

# Note: No app.run() needed for Vercel