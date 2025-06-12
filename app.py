from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import requests
import PyPDF2
from io import BytesIO
import os
import uuid
import random
import re

# Flask app setup
app = Flask(__name__, static_folder='static')
CORS(app)

# OpenAI configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
# Global session storage (in production, use Redis or database)
sessions = {}

def call_openai_api(prompt, temperature=0.7):
    """Call OpenAI API directly using requests"""
    headers = {
        'Authorization': f'Bearer {OPENAI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    data = {
        'model': 'gpt-3.5-turbo',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': temperature
    }
    
    try:
        response = requests.post(OPENAI_API_URL, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"OpenAI API Error: {e}")
        raise

class StudyPlanGenerator:
    """Generates progressive learning plans from topics or content"""
    
    def create_study_plan(self, topic_or_content, content_type="topic"):
        """Create a progressive study plan with building concepts"""
        
        if content_type == "topic":
            prompt = self._create_topic_study_plan_prompt(topic_or_content)
        else:  # PDF content
            prompt = self._create_content_study_plan_prompt(topic_or_content)
        
        try:
            response = call_openai_api(prompt, temperature=0.3)  # Lower temp for structured output
            study_plan = json.loads(response)
            return study_plan
        except json.JSONDecodeError as e:
            print(f"Study plan JSON parse error: {e}")
            # Fallback to simple plan
            return self._create_fallback_plan(topic_or_content)
    
    def _create_topic_study_plan_prompt(self, topic):
        return f"""
        Create a progressive learning study plan for: {topic}
        
        Design a sequence of concepts that build on each other, starting from basics and progressing to advanced.
        Each concept should prepare the student for the next one.
        
        IMPORTANT: Return ONLY valid JSON in this exact format:
        {{
            "topic": "{topic}",
            "total_concepts": 8,
            "learning_progression": [
                {{
                    "concept_id": 1,
                    "concept_name": "Basic concept name",
                    "description": "What this concept teaches",
                    "prerequisites": [],
                    "builds_to": [2, 3]
                }},
                {{
                    "concept_id": 2,
                    "concept_name": "Next concept name", 
                    "description": "What this concept teaches",
                    "prerequisites": [1],
                    "builds_to": [4]
                }}
            ],
            "difficulty_progression": "easy_to_hard",
            "estimated_questions": 10
        }}
        
        Create 6-10 concepts that form a logical learning progression.
        """
    
    def _create_content_study_plan_prompt(self, content):
        return f"""
        Analyze this content and create a progressive learning study plan:
        
        {content[:2000]}...
        
        Design a sequence of concepts from this content that build on each other.
        
        IMPORTANT: Return ONLY valid JSON in the same format as topic plans.
        """
    
    def _create_fallback_plan(self, topic):
        """Simple fallback plan if JSON parsing fails"""
        return {
            "topic": topic,
            "total_concepts": 6,
            "learning_progression": [
                {"concept_id": 1, "concept_name": f"Introduction to {topic}", "description": "Basic concepts", "prerequisites": [], "builds_to": [2]},
                {"concept_id": 2, "concept_name": f"Fundamentals of {topic}", "description": "Core principles", "prerequisites": [1], "builds_to": [3]},
                {"concept_id": 3, "concept_name": f"Intermediate {topic}", "description": "Building complexity", "prerequisites": [2], "builds_to": [4]},
                {"concept_id": 4, "concept_name": f"Advanced {topic}", "description": "Complex applications", "prerequisites": [3], "builds_to": [5]},
                {"concept_id": 5, "concept_name": f"Practical {topic}", "description": "Real-world usage", "prerequisites": [4], "builds_to": [6]},
                {"concept_id": 6, "concept_name": f"Mastery of {topic}", "description": "Expert level", "prerequisites": [5], "builds_to": []}
            ],
            "difficulty_progression": "easy_to_hard",
            "estimated_questions": 8
        }

class ProgressiveQuestionGenerator:
    """Generates questions that teach concepts progressively"""
    
    def generate_teaching_question(self, concept, study_plan, previous_concepts=None):
        """Generate a question that teaches a specific concept"""
        
        prompt = f"""
        Create a teaching question for this concept: {concept['concept_name']}
        
        Context: {concept['description']}
        Topic: {study_plan['topic']}
        
        This question should TEACH the concept through the learning process.
        Build on previous concepts: {previous_concepts or 'None (this is the first concept)'}
        
        CRITICAL REQUIREMENTS FOR EXPLANATIONS:
        1. Wrong answer explanations MUST be the most detailed and comprehensive
        2. Wrong answers are learning opportunities - explain WHY they're wrong with full reasoning
        3. Connect wrong answers to the correct concept to prevent future mistakes
        4. All explanations must be educational and helpful
        5. No lazy explanations like "doesn't match requirements"
        
        Question Requirements:
        1. Question should introduce and teach the concept progressively
        2. RANDOMIZE the correct answer position (A, B, C, or D) - do not favor A
        3. Make it educational and build on previous learning
        4. Each option should be plausible but clearly distinguishable
        
        IMPORTANT: Return ONLY valid JSON:
        {{
            "concept_id": {concept['concept_id']},
            "question": "Your progressive teaching question here",
            "options": {{
                "A": "Option A",
                "B": "Option B",
                "C": "Option C", 
                "D": "Option D"
            }},
            "correct_answer": "C",
            "explanations": {{
                "correct": "Comprehensive explanation of why this is correct, with examples, context, and how it builds on previous concepts",
                "A": "DETAILED explanation of why A is wrong: what concept it misses, what misconception it represents, how to avoid this mistake, and how it relates to the correct answer",
                "B": "DETAILED explanation of why B is wrong: specific reasoning, what makes it incorrect, educational context about the mistake",
                "C": "Reinforcing explanation of why C is correct, connecting to the learning progression",
                "D": "DETAILED explanation of why D is wrong: comprehensive reasoning, educational value, connection to correct concept"
            }},
            "teaching_focus": "What this question specifically teaches and how it builds on previous concepts",
            "difficulty": "easy"
        }}
        
        Remember: Wrong answer explanations should be MORE detailed than correct answer explanations because that's when students need the most help learning.
        """
        
        try:
            response = call_openai_api(prompt)
            question_data = json.loads(response)
            return question_data
        except json.JSONDecodeError as e:
            print(f"Question generation JSON error: {e}")
            return self._create_fallback_question(concept)
    
    def generate_mastery_questions(self, failed_concept, original_question, count=5):
        """Generate mastery questions for a concept the student got wrong"""
        
        prompt = f"""
        The student got this question wrong: {original_question['question']}
        Correct answer was: {original_question['correct_answer']}
        Concept: {failed_concept}
        
        Generate {count} mastery questions that test the SAME CONCEPT from different angles.
        
        CRITICAL REQUIREMENTS FOR MASTERY QUESTIONS:
        1. Test understanding, NOT memory or tricks
        2. Same core concept, different presentations and contexts
        3. Build confidence through fair, clear questions
        4. Help reinforce learning, not create confusion
        5. Questions should be similar but approached differently
        
        CRITICAL REQUIREMENTS FOR EXPLANATIONS:
        1. Wrong answer explanations MUST be extremely detailed and educational
        2. Since these are mastery checks, wrong answers indicate continued confusion
        3. Explain WHY each wrong answer is incorrect with full reasoning
        4. Connect explanations back to the core concept being tested
        5. Help students understand the concept from multiple angles
        6. No lazy explanations - every explanation should teach something valuable
        
        IMPORTANT: Return ONLY valid JSON array:
        [
            {{
                "mastery_question_id": 1,
                "original_concept": "{failed_concept}",
                "question": "Different way to ask about the same concept - rephrased or different context",
                "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
                "correct_answer": "C",
                "explanations": {{
                    "correct": "Comprehensive explanation of why this is correct, reinforcing the core concept understanding",
                    "A": "EXTREMELY DETAILED explanation of why A is wrong: what specific aspect of the concept it misses, what misconception it represents, how it differs from the correct understanding, and educational guidance",
                    "B": "EXTREMELY DETAILED explanation of why B is wrong: comprehensive reasoning about the mistake, educational context, connection to correct concept", 
                    "C": "Reinforcing explanation of correct answer, connecting to core concept mastery",
                    "D": "EXTREMELY DETAILED explanation of why D is wrong: thorough educational explanation, concept clarification, learning guidance"
                }},
                "mastery_focus": "Understanding verification of the core concept"
            }}
        ]
        
        Remember: These are mastery questions for students who already got this concept wrong. Wrong answer explanations need to be exceptionally detailed and educational to help them truly understand.
        """
        
        try:
            response = call_openai_api(prompt)
            mastery_questions = json.loads(response)
            return mastery_questions
        except json.JSONDecodeError as e:
            print(f"Mastery questions JSON error: {e}")
            return self._create_fallback_mastery_questions(failed_concept, count)
    
    def _create_fallback_question(self, concept):
        """Fallback question if generation fails"""
        return {
            "concept_id": concept['concept_id'],
            "question": f"What is a key aspect of {concept['concept_name']}?",
            "options": {
                "A": "Option A",
                "B": "Option B", 
                "C": "Option C",
                "D": "Option D"
            },
            "correct_answer": "B",
            "explanations": {
                "correct": "This demonstrates the core concept.",
                "A": "This is incorrect because it doesn't address the main concept.",
                "B": "This is correct as it captures the essential idea.",
                "C": "This is incorrect as it misses the key point.",
                "D": "This is incorrect because it's not relevant to the concept."
            },
            "teaching_focus": concept['description'],
            "difficulty": "medium"
        }
    
    def _create_fallback_mastery_questions(self, concept, count):
        """Fallback mastery questions if generation fails"""
        questions = []
        for i in range(count):
            questions.append({
                "mastery_question_id": i + 1,
                "original_concept": concept,
                "question": f"Mastery check {i+1}: Understanding {concept}",
                "options": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                "correct_answer": "A",
                "explanations": {
                    "correct": "This demonstrates understanding of the concept.",
                    "A": "Correct understanding of the concept.",
                    "B": "Incorrect interpretation.",
                    "C": "Misses the key point.",
                    "D": "Not relevant to the concept."
                },
                "mastery_focus": "Understanding verification"
            })
        return questions

class QuestionQueue:
    """Manages the progressive question queue with smart mastery insertion"""
    
    def __init__(self):
        self.main_questions = []
        self.mastery_questions = []
        self.current_index = 0
        self.completed_questions = []
        
    def add_main_questions(self, questions):
        """Add progressive teaching questions to the main queue"""
        self.main_questions.extend(questions)
    
    def insert_mastery_questions(self, mastery_questions, spacing=5):
        """Smart insertion of mastery questions with spacing"""
        if not mastery_questions:
            return
        
        # Calculate insertion points with spacing
        remaining_slots = len(self.main_questions) - self.current_index - 1
        
        if remaining_slots <= 0:
            # Add to end if no remaining main questions
            self.main_questions.extend(mastery_questions)
            return
        
        # Calculate optimal spacing
        if len(mastery_questions) == 1:
            insert_point = min(self.current_index + spacing, len(self.main_questions))
            self.main_questions.insert(insert_point, mastery_questions[0])
        else:
            # Distribute multiple mastery questions
            spacing_interval = max(2, remaining_slots // len(mastery_questions))
            
            for i, mastery_q in enumerate(mastery_questions):
                insert_point = min(
                    self.current_index + spacing + (i * spacing_interval),
                    len(self.main_questions)
                )
                self.main_questions.insert(insert_point, mastery_q)
    
    def get_next_question(self):
        """Get the next question in the queue"""
        if self.current_index >= len(self.main_questions):
            return None
        
        question = self.main_questions[self.current_index]
        return question
    
    def advance_queue(self):
        """Move to the next question"""
        if self.current_index < len(self.main_questions):
            self.completed_questions.append(self.main_questions[self.current_index])
            self.current_index += 1
    
    def get_progress(self):
        """Get current progress information"""
        total = len(self.main_questions)
        current = self.current_index
        return {
            "current_question": current + 1,
            "total_questions": total,
            "completed": current,
            "remaining": total - current,
            "progress_percentage": (current / total * 100) if total > 0 else 0
        }

def create_progressive_session(topic_or_content, session_type="topic"):
    """Create a new progressive learning session"""
    session_id = str(uuid.uuid4())
    
    # Generate study plan
    study_plan_generator = StudyPlanGenerator()
    study_plan = study_plan_generator.create_study_plan(topic_or_content, session_type)
    
    # Initialize session
    sessions[session_id] = {
        'id': session_id,
        'type': session_type,
        'content': topic_or_content,
        'study_plan': study_plan,
        'question_queue': QuestionQueue(),
        'question_generator': ProgressiveQuestionGenerator(),
        'current_concept_index': 0,
        'score': 100,
        'correct_answers': 0,
        'incorrect_answers': 0,
        'completed': False,
        'learned_concepts': []
    }
    
    return session_id

def generate_next_progressive_question(session_id):
    """Generate the next question in the progressive learning sequence"""
    if session_id not in sessions:
        raise ValueError("Session not found")
    
    session = sessions[session_id]
    study_plan = session['study_plan']
    queue = session['question_queue']
    generator = session['question_generator']
    
    # Check if we have a queued question
    next_question = queue.get_next_question()
    if next_question:
        return next_question
    
    # Generate next progressive question
    concept_index = session['current_concept_index']
    if concept_index >= len(study_plan['learning_progression']):
        # Learning complete
        session['completed'] = True
        return None
    
    current_concept = study_plan['learning_progression'][concept_index]
    previous_concepts = study_plan['learning_progression'][:concept_index] if concept_index > 0 else None
    
    # Generate teaching question
    question = generator.generate_teaching_question(current_concept, study_plan, previous_concepts)
    
    # Add metadata
    question['session_id'] = session_id
    question['question_number'] = queue.current_index + 1
    question['is_mastery_question'] = False
    question['progress'] = queue.get_progress()
    question['score'] = session['score']
    
    # Add to queue
    queue.add_main_questions([question])
    
    return question

# Routes
@app.route('/')
def home():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy", 
        "message": "ALP3 Progressive Learning API is running",
        "version": "3.0",
        "active_sessions": len(sessions)
    })

@app.route('/<path:filename>', methods=['GET'])
def static_files(filename):
    return send_from_directory(app.static_folder, filename)

@app.route('/api/start-progressive-session', methods=['POST'])
def start_progressive_session():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        session_type = data.get('type')
        
        if session_type == 'topic':
            topic = data.get('topic')
            if not topic:
                return jsonify({'error': 'Topic is required'}), 400
            
            # Create progressive session
            session_id = create_progressive_session(topic, 'topic')
            
            # Generate first question
            question_data = generate_next_progressive_question(session_id)
            
            if not question_data:
                return jsonify({'error': 'Failed to generate first question'}), 500
            
            return jsonify(question_data)
            
        elif session_type == 'file':
            # Handle file upload (simplified for now)
            return jsonify({'error': 'File upload not implemented yet'}), 501
            
        else:
            return jsonify({'error': 'Invalid session type'}), 400
            
    except Exception as e:
        print(f"Start progressive session error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/submit-progressive-answer', methods=['POST'])
def submit_progressive_answer():
    try:
        data = request.get_json()
        
        session_id = data.get('session_id')
        selected_answer = data.get('selected_answer')
        current_question = data.get('current_question')
        
        if not all([session_id, selected_answer, current_question]):
            return jsonify({'error': 'Missing required data'}), 400
        
        if session_id not in sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = sessions[session_id]
        queue = session['question_queue']
        generator = session['question_generator']
        
        correct_answer = current_question.get('correct_answer')
        is_correct = selected_answer == correct_answer
        
        # Update session stats
        if is_correct:
            session['correct_answers'] += 1
            session['score'] += 10
            
            # Mark concept as learned if this was a main teaching question
            if not current_question.get('is_mastery_question', False):
                concept_id = current_question.get('concept_id')
                if concept_id and concept_id not in session['learned_concepts']:
                    session['learned_concepts'].append(concept_id)
                    session['current_concept_index'] += 1
        else:
            session['incorrect_answers'] += 1
            session['score'] -= 5
            
            # Generate mastery questions for the failed concept
            if not current_question.get('is_mastery_question', False):
                concept_name = current_question.get('teaching_focus', 'Unknown concept')
                mastery_questions = generator.generate_mastery_questions(
                    concept_name, current_question, count=5
                )
                
                # Mark as mastery questions and add metadata
                for mq in mastery_questions:
                    mq['is_mastery_question'] = True
                    mq['session_id'] = session_id
                    mq['original_failed_concept'] = concept_name
                
                # Insert with smart spacing
                queue.insert_mastery_questions(mastery_questions, spacing=5)
        
        # Advance queue
        queue.advance_queue()
        
        # Prepare response with explanations
        explanations = current_question.get('explanations', {})
        
        # Enhanced explanation for the selected answer
        if is_correct:
            explanation_text = explanations.get('correct', 'Correct!')
        else:
            # Detailed wrong answer explanation
            wrong_explanation = explanations.get(selected_answer, 'This answer is incorrect.')
            correct_explanation = explanations.get('correct', 'No explanation available.')
            
            explanation_text = f"❌ Your answer ({selected_answer}): {wrong_explanation}\n\n✅ Correct answer ({correct_answer}): {correct_explanation}"
        
        # Check if session is complete
        progress = queue.get_progress()
        if queue.current_index >= len(queue.main_questions):
            session['completed'] = True
            
            return jsonify({
                'session_complete': True,
                'final_score': session['score'],
                'total_questions': len(queue.completed_questions),
                'learned_concepts': len(session['learned_concepts']),
                'summary': {
                    'correct_answers': session['correct_answers'],
                    'incorrect_answers': session['incorrect_answers'],
                    'concepts_mastered': session['learned_concepts']
                },
                'is_correct': is_correct,
                'explanation': explanation_text
            })
        
        # Generate next question
        try:
            next_question = generate_next_progressive_question(session_id)
            
            if not next_question:
                # No more questions, session complete
                session['completed'] = True
                return jsonify({
                    'session_complete': True,
                    'final_score': session['score'],
                    'total_questions': len(queue.completed_questions),
                    'learned_concepts': len(session['learned_concepts']),
                    'is_correct': is_correct,
                    'explanation': explanation_text
                })
            
            return jsonify({
                'is_correct': is_correct,
                'explanation': explanation_text,
                'next_question': next_question,
                'session_complete': False,
                'progress': progress,
                'score': session['score']
            })
            
        except Exception as e:
            print(f"Error generating next question: {e}")
            return jsonify({'error': 'Failed to generate next question'}), 500
        
    except Exception as e:
        print(f"Submit progressive answer error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-session-progress', methods=['POST'])
def get_session_progress():
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if not session_id or session_id not in sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = sessions[session_id]
        queue = session['question_queue']
        
        return jsonify({
            'session_id': session_id,
            'progress': queue.get_progress(),
            'score': session['score'],
            'learned_concepts': len(session['learned_concepts']),
            'total_concepts': len(session['study_plan']['learning_progression']),
            'correct_answers': session['correct_answers'],
            'incorrect_answers': session['incorrect_answers'],
            'completed': session['completed']
        })
        
    except Exception as e:
        print(f"Get session progress error: {e}")
        return jsonify({'error': str(e)}), 500
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)