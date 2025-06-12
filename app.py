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
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import copy
from concurrent.futures import ThreadPoolExecutor
import time
from collections import defaultdict

load_dotenv()

# Thread pool for background batch generation (conservative worker count)
executor = ThreadPoolExecutor(max_workers=4)  # Reduced for better resource management

# Simple rate limiting for session creation
session_creation_times = defaultdict(list)
MAX_SESSIONS_PER_MINUTE = 5  # Limit sessions per IP per minute

def check_rate_limit(client_ip):
    """Check if client is within rate limits for session creation"""
    current_time = time.time()
    minute_ago = current_time - 60
    
    # Clean old entries
    session_creation_times[client_ip] = [
        t for t in session_creation_times[client_ip] if t > minute_ago
    ]
    
    # Check if under limit
    if len(session_creation_times[client_ip]) >= MAX_SESSIONS_PER_MINUTE:
        return False
    
    # Record this request
    session_creation_times[client_ip].append(current_time)
    return True

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app setup
app = Flask(__name__, static_folder='static')

# CORS configuration - restrict to specific origins in production
CORS(app, origins=['http://localhost:3000', 'http://localhost:8080', 'http://127.0.0.1:3000', 'http://127.0.0.1:8080'])

# Configuration from environment variables
class Config:
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-2024-05-13')  # Configurable model with reliable default
    OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    SESSION_TIMEOUT_HOURS = 24

# Validate required environment variables
if not Config.OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY environment variable is required")
    raise ValueError("OPENAI_API_KEY environment variable is required. Please set it before running the application.")

# Set Flask configuration
app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH

# Global session storage (in production, use Redis or database)
sessions = {}

# Custom exceptions
class APIError(Exception):
    def __init__(self, message, status_code=500):
        self.message = message
        self.status_code = status_code

class ValidationError(Exception):
    def __init__(self, message):
        self.message = message

# Input validation functions
def validate_session_data(data):
    """Validate session creation data"""
    if not data:
        raise ValidationError('No data provided')
    
    session_type = data.get('type')
    if not session_type:
        raise ValidationError('Session type is required')
    
    if session_type not in ['topic', 'file']:
        raise ValidationError('Invalid session type. Must be "topic" or "file"')
    
    if session_type == 'topic':
        topic = data.get('topic')
        if not topic or not topic.strip():
            raise ValidationError('Topic is required for topic-based sessions')
        if len(topic.strip()) > 200:
            raise ValidationError('Topic must be less than 200 characters')
    
    return True

def validate_answer_data(data):
    """Validate answer submission data"""
    required_fields = ['session_id', 'selected_answer', 'current_question']
    
    for field in required_fields:
        if not data.get(field):
            raise ValidationError(f'{field} is required')
    
    selected_answer = data.get('selected_answer')
    if selected_answer.upper() not in ['A', 'B', 'C', 'D']:
        raise ValidationError('Selected answer must be A, B, C, or D')
    
    return True

def sanitize_input(text):
    """Basic input sanitization"""
    if not isinstance(text, str):
        return text
    
    # Remove potentially harmful characters
    text = re.sub(r'[<>"\']', '', text)
    return text.strip()

def normalize_option_keys(question):
    """Normalize option keys to uppercase and ensure all A,B,C,D exist"""
    if 'options' not in question:
        return question
    
    options = question['options']
    normalized_options = {}
    
    # Convert all keys to uppercase
    for key, value in options.items():
        normalized_key = key.upper()
        if normalized_key in ['A', 'B', 'C', 'D']:
            normalized_options[normalized_key] = value
    
    # Ensure all required options exist
    required_options = ['A', 'B', 'C', 'D']
    for opt in required_options:
        if opt not in normalized_options:
            normalized_options[opt] = f"Option {opt}"
    
    question['options'] = normalized_options
    
    # Normalize correct_answer
    if 'correct_answer' in question:
        question['correct_answer'] = question['correct_answer'].upper()
    
    return question

def shuffle_question_options(question):
    """Shuffle options randomly and update correct_answer accordingly"""
    if 'options' not in question or 'correct_answer' not in question:
        return question
    
    # Create a copy to avoid modifying the original
    shuffled_question = copy.deepcopy(question)
    
    # Get the correct answer text
    correct_text = shuffled_question['options'][shuffled_question['correct_answer']]
    
    # Create list of option texts
    option_texts = [
        shuffled_question['options']['A'],
        shuffled_question['options']['B'], 
        shuffled_question['options']['C'],
        shuffled_question['options']['D']
    ]
    
    # Shuffle the texts
    random.shuffle(option_texts)
    
    # Reassign to A, B, C, D
    shuffled_question['options'] = {
        'A': option_texts[0],
        'B': option_texts[1],
        'C': option_texts[2],
        'D': option_texts[3]
    }
    
    # Find new position of correct answer
    for key, text in shuffled_question['options'].items():
        if text == correct_text:
            shuffled_question['correct_answer'] = key
            break
    
    # Update explanations to match new positions
    if 'explanations' in shuffled_question:
        old_explanations = shuffled_question['explanations'].copy()
        new_explanations = {}
        
        # Map explanations to new positions
        for new_key, text in shuffled_question['options'].items():
            # Find which old key had this text
            for old_key, old_text in question['options'].items():
                if old_text == text and old_key in old_explanations:
                    new_explanations[new_key] = old_explanations[old_key]
                    break
        
        # Ensure correct explanation is updated
        if 'correct' in old_explanations:
            new_explanations['correct'] = old_explanations['correct']
        
        shuffled_question['explanations'] = new_explanations
    
    return shuffled_question

def call_openai_api(prompt, system_message=None, temperature=0.3, max_retries=3, response_format=None):
    """Call OpenAI API with improved parameters and error handling"""
    headers = {
        'Authorization': f'Bearer {Config.OPENAI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    messages = []
    if system_message:
        messages.append({'role': 'system', 'content': system_message})
    messages.append({'role': 'user', 'content': prompt})
    
    data = {
        'model': Config.OPENAI_MODEL,  # Configurable model from environment
        'messages': messages,
        'temperature': temperature,
        'max_tokens': 4096  # Appropriate for gpt-3.5-turbo
    }
    
    # Add response format if specified
    if response_format:
        data['response_format'] = response_format
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Making OpenAI API call (attempt {attempt + 1}) with model {Config.OPENAI_MODEL}")
            response = requests.post(
                Config.OPENAI_API_URL, 
                headers=headers, 
                json=data, 
                timeout=60  # Standard timeout for gpt-3.5-turbo
            )
            response.raise_for_status()
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            logger.info("OpenAI API call successful")
            return content
            
        except requests.exceptions.RequestException as e:
            logger.error(f"OpenAI API request error (attempt {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                raise APIError(f"OpenAI API request failed after {max_retries} attempts: {str(e)}")
        except KeyError as e:
            logger.error(f"OpenAI API response format error: {e}")
            raise APIError("Invalid response format from OpenAI API")
        except Exception as e:
            logger.error(f"Unexpected error in OpenAI API call: {e}")
            if attempt == max_retries - 1:
                raise APIError(f"OpenAI API call failed: {str(e)}")

def cleanup_expired_sessions():
    """Remove expired sessions to prevent memory leaks"""
    current_time = datetime.now()
    expired_sessions = []
    
    for session_id, session in sessions.items():
        session_time = session.get('created_at', current_time)
        if current_time - session_time > timedelta(hours=Config.SESSION_TIMEOUT_HOURS):
            expired_sessions.append(session_id)
    
    for session_id in expired_sessions:
        del sessions[session_id]
        logger.info(f"Cleaned up expired session: {session_id}")

def extract_pdf_text(file_content):
    """Extract text from PDF file content"""
    try:
        pdf_reader = PyPDF2.PdfReader(BytesIO(file_content))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        raise APIError("Failed to extract text from PDF file")

class StudyPlanGenerator:
    """Generates progressive learning plans from topics or content"""
    
    def create_study_plan(self, topic_or_content, content_type="topic"):
        """Create a progressive study plan with building concepts"""
        
        # Sanitize input
        topic_or_content = sanitize_input(topic_or_content)
        
        if content_type == "topic":
            prompt = self._create_topic_study_plan_prompt(topic_or_content)
        else:  # PDF content
            prompt = self._create_content_study_plan_prompt(topic_or_content)
        
        system_message = "You are an educational curriculum designer. Output only valid JSON matching the schema provided."
        
        try:
            response = call_openai_api(
                prompt, 
                system_message=system_message,
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            study_plan = json.loads(response)
            
            # Validate study plan structure
            if not self._validate_study_plan(study_plan):
                logger.warning("Generated study plan failed validation, using fallback")
                return self._create_fallback_plan(topic_or_content)
            
            logger.info(f"Successfully created study plan for: {topic_or_content[:50]}...")
            return study_plan
            
        except json.JSONDecodeError as e:
            logger.error(f"Study plan JSON parse error: {e}")
            return self._create_fallback_plan(topic_or_content)
        except Exception as e:
            logger.error(f"Study plan generation error: {e}")
            return self._create_fallback_plan(topic_or_content)
    
    def _validate_study_plan(self, study_plan):
        """Validate study plan structure"""
        required_fields = ['topic', 'total_concepts', 'learning_progression']
        
        for field in required_fields:
            if field not in study_plan:
                return False
        
        if not isinstance(study_plan['learning_progression'], list):
            return False
        
        if len(study_plan['learning_progression']) == 0:
            return False
        
        return True
    
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
            "estimated_questions": 20
        }}
        
        Create 6-10 concepts that form a logical learning progression.
        """
    
    def _create_content_study_plan_prompt(self, content):
        # Limit content length to prevent token overflow
        content_preview = content[:2000] if len(content) > 2000 else content
        
        return f"""
        Analyze this content and create a progressive learning study plan:
        
        {content_preview}...
        
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
            "estimated_questions": 20
        }

class ProgressiveQuestionGenerator:
    """Generates questions that teach concepts progressively"""
    
    def __init__(self):
        # Define the 4 batches with their characteristics
        self.batches = [
            {
                "name": "Foundation",
                "questions": "1-5",
                "difficulty": "easy",
                "focus": "Introduce basic principles and definitions through scenarios. Build fundamental understanding."
            },
            {
                "name": "Core Mechanisms", 
                "questions": "6-10",
                "difficulty": "easy-medium",
                "focus": "Explain how things work. Connect structure to function."
            },
            {
                "name": "Applications",
                "questions": "11-15", 
                "difficulty": "medium",
                "focus": "Real-world scenarios and problem-solving. 'What would happen if...' questions."
            },
            {
                "name": "Mastery",
                "questions": "16-20",
                "difficulty": "medium-hard to hard", 
                "focus": "Advanced problem-solving. Predict outcomes and design solutions."
            }
        ]
    
    def generate_all_progressive_questions(self, study_plan, count=20):
        """Generate all 20 progressive questions in 4 batches of 5 questions each"""
        
        all_questions = []
        
        system_message = "You are an assessment engine. Output only valid JSON matching the schema the user provides, no prose."
        
        for i, batch in enumerate(self.batches):
            try:
                logger.info(f"Generating batch {i+1}/4: {batch['name']} questions")
                
                batch_questions = self._generate_question_batch(
                    study_plan, 
                    batch, 
                    start_id=i*5 + 1,
                    system_message=system_message
                )
                
                if batch_questions:
                    all_questions.extend(batch_questions)
                else:
                    logger.warning(f"Batch {i+1} failed, using fallback questions")
                    fallback_questions = self._create_fallback_questions_batch(study_plan, i*5 + 1, 5)
                    all_questions.extend(fallback_questions)
                    
            except Exception as e:
                logger.error(f"Error generating batch {i+1}: {e}")
                fallback_questions = self._create_fallback_questions_batch(study_plan, i*5 + 1, 5)
                all_questions.extend(fallback_questions)
        
        # Shuffle options for all questions
        shuffled_questions = []
        for question in all_questions:
            normalized_question = normalize_option_keys(question)
            shuffled_question = shuffle_question_options(normalized_question)
            shuffled_questions.append(shuffled_question)
        
        logger.info(f"Successfully generated {len(shuffled_questions)} progressive questions in 4 batches")
        return shuffled_questions
    
    def _generate_question_batch(self, study_plan, batch_info, start_id, system_message):
        """Generate a batch of 5 questions"""
        
        prompt = f"""
        You are creating a progressive learning experience for the topic: {study_plan['topic']}
        
        BATCH: {batch_info['name']} (Questions {batch_info['questions']})
        DIFFICULTY: {batch_info['difficulty']}
        FOCUS: {batch_info['focus']}
        
        EXAMPLE OF PERFECT QUESTION QUALITY (Bio 1 example):
        
        {{
          "question_id": 12,
          "concept_id": 4,
          "question": "If a genetic mutation disables lysosomal enzymes, which outcome is most likely?",
          "options": {{
            "A": "Failure of DNA replication in the nucleus",
            "B": "Accumulation of undigested macromolecules in the cell", 
            "C": "Loss of ATP synthesis in mitochondria",
            "D": "Immediate rupture of the plasma membrane"
          }},
          "correct_answer": "B",
          "explanations": {{
            "correct": "Lysosomes degrade waste; without enzymes, debris builds up (e.g., Tay-Sachs disease).",
            "A": "Lysosomes are not directly involved in nuclear DNA synthesis.",
            "B": "Lysosomes degrade waste; without enzymes, debris builds up (e.g., Tay-Sachs disease).",
            "C": "Mitochondrial ATP production does not depend on lysosomal enzymes.",
            "D": "Membrane integrity is not directly compromised by lysosomal inactivity."
          }},
          "teaching_focus": "Lysosomal function and genetic diseases",
          "difficulty": "hard"
        }}
        
        QUALITY REQUIREMENTS - MATCH THIS STANDARD:
        1. **Real scenarios and applications** - not generic "What is..." questions
        2. **Specific, educational explanations** - explain WHY each answer is wrong with scientific reasoning
        3. **Progressive difficulty** - match the batch difficulty level
        4. **Professional scientific language** - use proper terminology
        5. **Connect to real examples** - diseases, phenomena, experiments
        
        LEARNING PROGRESSION FOR {study_plan['topic']}:
        {json.dumps(study_plan['learning_progression'], indent=2)}
        
        QUESTION STYLE EXAMPLES FOR INSPIRATION:
        - "A scientist observes that [specific scenario]. What explains this phenomenon?"
        - "If [specific condition] occurs, which outcome is most likely?"
        - "Which sequence correctly traces [specific process]?"
        - "A patient with [specific condition] would most likely experience..."
        - "Two identical [objects] are placed in different [conditions]. Which would..."
        
        AVOID THESE PATTERNS:
        ❌ "What is the definition of..."
        ❌ "Which of the following describes..."
        ❌ "What is a key aspect of..."
        ❌ Generic, memorization-based questions
        
        EXPLANATION REQUIREMENTS:
        - Wrong answers: Specific scientific reasoning for why it's incorrect
        - Include real examples, diseases, or phenomena when relevant
        - Teach additional concepts beyond just the answer
        - Use precise scientific terminology
        
        IMPORTANT: Return ONLY JSON exactly like:
        {{
          "questions": [
            {{
                "question_id": {start_id},
                "concept_id": 1,
                "question": "Specific scenario or application question",
                "options": {{
                    "A": "Specific, scientifically accurate option",
                    "B": "Another plausible but incorrect option",
                    "C": "The correct answer with clear scientific basis", 
                    "D": "A common misconception or alternative explanation"
                }},
                "correct_answer": "C",
                "explanations": {{
                    "correct": "Scientific explanation of why this is correct, with examples or connections",
                    "A": "Specific scientific reasoning for why this is incorrect",
                    "B": "Clear explanation of the scientific error in this option",
                    "C": "Scientific explanation of why this is correct, with examples or connections",
                    "D": "Educational explanation of why this misconception is wrong"
                }},
                "teaching_focus": "Specific concept or principle this question teaches",
                "difficulty": "{batch_info['difficulty'].split()[0]}"
            }}
          ]
        }}
        
        Generate exactly 5 questions for the {batch_info['name']} batch that match the quality and style of the Bio 1 example.
        """
        
        try:
            response = call_openai_api(
                prompt, 
                system_message=system_message,
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            parsed = json.loads(response)
            questions = parsed["questions"]  # Extract questions array from object
            
            # Validate it's an array with 5 questions
            if not isinstance(questions, list) or len(questions) != 5:
                logger.warning(f"Batch returned {len(questions) if isinstance(questions, list) else 'non-array'} questions, expected 5")
                return None
            
            # Validate each question
            validated_questions = []
            for q in questions:
                if self._validate_question(q):
                    validated_questions.append(q)
            
            if len(validated_questions) < 3:  # Need at least 3 valid questions
                logger.warning(f"Only {len(validated_questions)} valid questions in batch")
                return None
            
            return validated_questions
            
        except json.JSONDecodeError as e:
            logger.error(f"Batch JSON parse error: {e}")
            return None
        except Exception as e:
            logger.error(f"Batch generation error: {e}")
            return None
    
    def _create_fallback_questions_batch(self, study_plan, start_id, count):
        """Create fallback questions for a batch"""
        questions = []
        concepts = study_plan['learning_progression']
        topic = study_plan['topic']
        
        for i in range(count):
            concept_index = (start_id + i - 1) % len(concepts)
            concept = concepts[concept_index]
            
            questions.append({
                "question_id": start_id + i,
                "concept_id": concept['concept_id'],
                "question": f"What is a key aspect of {concept['concept_name']}?",
                "options": {
                    "A": f"Understanding the basic principles of {concept['concept_name']}",
                    "B": f"Memorizing facts about {concept['concept_name']}",
                    "C": f"Ignoring the context of {concept['concept_name']}",
                    "D": f"Skipping the fundamentals of {concept['concept_name']}"
                },
                "correct_answer": "A",
                "explanations": {
                    "correct": f"Understanding the basic principles is essential for mastering {concept['concept_name']}.",
                    "A": f"Correct! Understanding basic principles provides a solid foundation for {concept['concept_name']}.",
                    "B": f"Incorrect. While facts are important, understanding principles is more valuable than mere memorization.",
                    "C": f"Incorrect. Context is crucial for understanding how {concept['concept_name']} applies in real situations.",
                    "D": f"Incorrect. Fundamentals are the building blocks - skipping them leads to gaps in understanding."
                },
                "teaching_focus": concept['description'],
                "difficulty": "easy" if start_id <= 5 else "medium" if start_id <= 15 else "hard"
            })
        
        return questions
    
    def generate_mastery_questions(self, failed_concept, original_question, count=5):
        """Generate mastery questions for a concept the student got wrong"""
        
        system_message = "You are an assessment engine. Output only valid JSON matching the schema the user provides, no prose."
        
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
        
        IMPORTANT: Return ONLY JSON exactly like:
        {{
          "questions": [
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
        }}
        
        Remember: These are mastery questions for students who already got this concept wrong. Wrong answer explanations need to be exceptionally detailed and educational to help them truly understand.
        """
        
        try:
            response = call_openai_api(
                prompt, 
                system_message=system_message,
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            parsed = json.loads(response)
            mastery_questions = parsed["questions"]  # Extract questions array from object
            
            # Ensure it's a list
            if not isinstance(mastery_questions, list):
                mastery_questions = [mastery_questions] if mastery_questions else []
            
            # Validate and normalize each mastery question
            validated_questions = []
            for mq in mastery_questions:
                if self._validate_question(mq):
                    normalized_mq = normalize_option_keys(mq)
                    shuffled_mq = shuffle_question_options(normalized_mq)
                    validated_questions.append(shuffled_mq)
            
            if not validated_questions:
                logger.warning("No valid mastery questions generated, using fallback")
                return self._create_fallback_mastery_questions(failed_concept, count)
            
            logger.info(f"Successfully generated {len(validated_questions)} mastery questions")
            return validated_questions
            
        except json.JSONDecodeError as e:
            logger.error(f"Mastery questions JSON error: {e}")
            return self._create_fallback_mastery_questions(failed_concept, count)
        except Exception as e:
            logger.error(f"Mastery questions generation error: {e}")
            return self._create_fallback_mastery_questions(failed_concept, count)
    
    def _validate_question(self, question_data):
        """Validate question structure with improved checks"""
        required_fields = ['question', 'options', 'correct_answer', 'explanations']
        
        for field in required_fields:
            if field not in question_data:
                logger.warning(f"Question missing required field: {field}")
                return False
        
        # Validate options
        options = question_data.get('options', {})
        required_option_keys = ['A', 'B', 'C', 'D']
        
        # Normalize option keys first
        normalized_options = {}
        for key, value in options.items():
            normalized_key = key.upper()
            if normalized_key in required_option_keys:
                normalized_options[normalized_key] = value
        
        if not all(key in normalized_options for key in required_option_keys):
            logger.warning(f"Question missing required options. Has: {list(normalized_options.keys())}")
            return False
        
        # Validate correct answer
        correct_answer = question_data.get('correct_answer', '').upper()
        if correct_answer not in required_option_keys:
            logger.warning(f"Invalid correct_answer: {correct_answer}")
            return False
        
        # Validate explanations
        explanations = question_data.get('explanations', {})
        if 'correct' not in explanations:
            logger.warning("Question missing 'correct' explanation")
            return False
        
        return True
    
    def _create_fallback_mastery_questions(self, concept, count):
        """Fallback mastery questions if generation fails"""
        questions = []
        for i in range(count):
            question = {
                "mastery_question_id": i + 1,
                "original_concept": concept,
                "question": f"Mastery check {i+1}: Which best describes {concept}?",
                "options": {
                    "A": f"A fundamental aspect of {concept}",
                    "B": f"An unrelated concept to {concept}",
                    "C": f"A complex variation of {concept}",
                    "D": f"An opposite of {concept}"
                },
                "correct_answer": "A",
                "explanations": {
                    "correct": f"This demonstrates understanding of {concept}.",
                    "A": f"Correct! This shows proper understanding of {concept}.",
                    "B": f"Incorrect. This is not related to {concept}.",
                    "C": f"Incorrect. This is too complex for the basic concept.",
                    "D": f"Incorrect. This contradicts the concept of {concept}."
                },
                "mastery_focus": "Understanding verification"
            }
            
            # Normalize and shuffle
            normalized_question = normalize_option_keys(question)
            shuffled_question = shuffle_question_options(normalized_question)
            questions.append(shuffled_question)
            
        return questions

def _generate_batches_async(study_plan, start_index, qgen, queue):
    """Background job: create batches 2-4 and append to queue in correct order"""
    # Generate all remaining batches
    batch_results = {}
    
    for i in range(start_index, 4):
        batch = qgen._generate_question_batch(
            study_plan, qgen.batches[i], start_id=i*5+1,
            system_message="You are an assessment engine. Output only valid JSON matching the schema the user provides, no prose."
        )
        if not batch:
            # Apply same normalization and shuffling to fallback questions
            fallback_batch = qgen._create_fallback_questions_batch(study_plan, i*5+1, 5)
            batch = [shuffle_question_options(normalize_option_keys(q)) for q in fallback_batch]
        else:
            # Apply normalization and shuffling to generated questions
            batch = [shuffle_question_options(normalize_option_keys(q)) for q in batch]
        
        # Store batch with its index to maintain order
        batch_results[i] = batch
    
    # Insert batches in correct order (Foundation→Core→Applications→Mastery)
    for i in sorted(batch_results.keys()):
        queue.main_questions.extend(batch_results[i])

# ------------------------------------------------------------------
#  BACKGROUND TASK: generate 5 mastery questions without blocking
# ------------------------------------------------------------------
def _async_generate_and_insert_mastery(session_id, concept_name, original_q):
    """
    Runs inside ThreadPoolExecutor.
    Generates mastery questions for a failed concept and inserts them
    into the existing QuestionQueue with smart spacing.
    """
    session = sessions.get(session_id)
    if not session or session.get("completed"):
        return  # Session no longer active

    generator = session["question_generator"]
    queue     = session["question_queue"]

    try:
        mastery_qs = generator.generate_mastery_questions(
            concept_name,
            original_q,
            count=5
        )

        # tag questions before inserting
        for mq in mastery_qs:
            mq["is_mastery_question"]    = True
            mq["session_id"]             = session_id
            mq["original_failed_concept"] = concept_name

        queue.insert_mastery_questions(mastery_qs, spacing=3)
        logger.info("Inserted %s mastery questions for session %s",
                    len(mastery_qs), session_id)

    except Exception as e:
        logger.error("Async mastery generation failed (%s): %s",
                     session_id, e)
# ------------------------------------------------------------------

class QuestionQueue:
    """Manages the progressive question queue with smart mastery insertion"""
    
    def __init__(self, pre_generated_questions):
        self.main_questions = pre_generated_questions.copy()
        self.current_index = 0
        self.completed_questions = []
        
    def insert_mastery_questions(self, mastery_questions, spacing=3):
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
        """Get current progress statistics"""
        total = len(self.main_questions)
        current = self.current_index
        loading = len(self.main_questions) < 20  # Add loading flag
        return {
            "current_question": current + 1,
            "total_questions": total,
            "completed": current,
            "remaining": total - current,
            "progress_percentage": (current / total * 100) if total > 0 else 0,
            "loading": loading
        }

def create_progressive_session(topic_or_content, session_type="topic"):
    """Create a new progressive learning session with pre-generated questions"""
    session_id = str(uuid.uuid4())
    
    # Clean up expired sessions periodically
    cleanup_expired_sessions()
    
    # Generate study plan
    study_plan_generator = StudyPlanGenerator()
    study_plan = study_plan_generator.create_study_plan(topic_or_content, session_type)
    
    # ---------- batch-0 sync ----------
    qgen = ProgressiveQuestionGenerator()

    batch0 = qgen._generate_question_batch(
        study_plan, qgen.batches[0], start_id=1,
        system_message="You are an assessment engine. Output only valid JSON matching the schema the user provides, no prose."
    )

    # ───── simple diagnostics ───────────────────────────────────────────
    print("DEBUG - batch0 returned:", 0 if batch0 is None else len(batch0))
    # --------------------------------------------------------------------

    if not batch0 or len(batch0) == 0:          # [] or None  → fallback
        print("DEBUG - using fallback batch0")
        batch0 = qgen._create_fallback_questions_batch(study_plan, 1, 5)

    if not batch0 or len(batch0) == 0:          # still empty → hard error
        raise APIError("No questions generated for batch-0", 500)

    print("DEBUG - batch0 after fallback:", len(batch0))

    questions = [shuffle_question_options(normalize_option_keys(q)) for q in batch0]
    print("DEBUG - questions entering queue:", len(questions))

    queue = QuestionQueue(questions)


    # ---------- batches 1-3 async ----------
    executor.submit(_generate_batches_async, study_plan, 1, qgen, queue)
    
    # Initialize session with first batch ready
    sessions[session_id] = {
        'id': session_id,
        'type': session_type,
        'content': topic_or_content,
        'study_plan': study_plan,
        'question_queue': queue,
        'question_generator': qgen,
        'current_concept_index': 0,
        'score': 100,
        'correct_answers': 0,
        'incorrect_answers': 0,
        'completed': False,
        'learned_concepts': [],
        'created_at': datetime.now()
    }
    
    logger.info(f"Created new session with first batch ready: {session_id}")
    return session_id

def get_next_progressive_question(session_id):
    """Get the next pre-generated question (instant response)"""
    if session_id not in sessions:
        raise APIError("Session not found", 404)
    
    session = sessions[session_id]
    queue = session['question_queue']
    
    # Get next pre-generated question (no OpenAI call needed)
    next_question = queue.get_next_question()
    if not next_question:
        # All questions completed
        session['completed'] = True
        return None
    
    # Add metadata
    next_question['session_id'] = session_id
    next_question['question_number'] = queue.current_index + 1
    next_question['is_mastery_question'] = next_question.get('mastery_question_id') is not None
    next_question['progress'] = queue.get_progress()
    next_question['score'] = session['score']
    
    return next_question

# Error handlers
@app.errorhandler(ValidationError)
def handle_validation_error(e):
    logger.warning(f"Validation error: {e.message}")
    return jsonify({'error': e.message}), 400

@app.errorhandler(APIError)
def handle_api_error(e):
    logger.error(f"API error: {e.message}")
    return jsonify({'error': e.message}), e.status_code

@app.errorhandler(413)
def handle_file_too_large(e):
    logger.warning("File upload too large")
    return jsonify({'error': 'File too large. Maximum size is 16MB.'}), 413

@app.errorhandler(500)
def handle_internal_error(e):
    logger.error(f"Internal server error: {e}")
    return jsonify({'error': 'Internal server error'}), 500

# Routes
@app.route('/')
def home():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy", 
        "message": "ALP3 Progressive Learning API is running",
        "version": "4.1",
        "model": Config.OPENAI_MODEL,
        "active_sessions": len(sessions),
        "environment": "development" if Config.DEBUG else "production"
    })

@app.route('/<path:filename>', methods=['GET'])
def static_files(filename):
    return send_from_directory(app.static_folder, filename)

@app.route('/api/start-progressive-session', methods=['POST'])
def start_progressive_session():
    try:
        # Check rate limiting
        client_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'unknown'))
        if not check_rate_limit(client_ip):
            raise APIError('Rate limit exceeded. Please wait before creating another session.', 429)
        
        data = request.get_json()
        
        # Validate input
        validate_session_data(data)
        
        session_type = data.get('type')
        
        if session_type == 'topic':
            topic = sanitize_input(data.get('topic'))
            
            # Create progressive session with pre-generated questions
            session_id = create_progressive_session(topic, 'topic')
            
            # Get first pre-generated question (instant)
            question_data = get_next_progressive_question(session_id)
            
            if not question_data:
                raise APIError('Failed to get first question', 500)
            
            logger.info(f"Started progressive session for topic: {topic} (IP: {client_ip})")
            return jsonify(question_data)
            
        elif session_type == 'file':
            # Handle file upload
            if 'file' not in request.files:
                raise ValidationError('No file provided')
            
            file = request.files['file']
            if file.filename == '':
                raise ValidationError('No file selected')
            
            if not file.filename.lower().endswith('.pdf'):
                raise ValidationError('Only PDF files are supported')
            
            # Extract text from PDF
            file_content = file.read()
            extracted_text = extract_pdf_text(file_content)
            
            if not extracted_text.strip():
                raise APIError('Could not extract text from PDF file')
            
            # Create progressive session with PDF content and pre-generated questions
            session_id = create_progressive_session(extracted_text, 'file')
            
            # Get first pre-generated question (instant)
            question_data = get_next_progressive_question(session_id)
            
            if not question_data:
                raise APIError('Failed to get first question from PDF content', 500)
            
            logger.info(f"Started progressive session for PDF: {file.filename}")
            return jsonify(question_data)
            
        else:
            raise ValidationError('Invalid session type')
            
    except ValidationError as e:
        raise e
    except APIError as e:
        raise e
    except Exception as e:
        logger.error(f"Start progressive session error: {e}")
        raise APIError(f'Failed to start session: {str(e)}', 500)
@app.route('/api/submit-progressive-answer', methods=['POST'])
def submit_progressive_answer():
    try:
        data = request.get_json()

        # 1 — validate payload
        validate_answer_data(data)

        session_id       = data.get("session_id")
        selected_answer  = data.get("selected_answer", "").upper()
        current_question = data.get("current_question")

        if session_id not in sessions:
            raise APIError("Session not found", 404)

        session   = sessions[session_id]
        queue     = session["question_queue"]
        generator = session["question_generator"]   # still needed later

        correct_answer = current_question.get("correct_answer", "").upper()
        is_correct     = selected_answer == correct_answer

        # ────────────────────────────────────────────────────────────
        # 2 — update score / schedule mastery questions (non-blocking)
        # ────────────────────────────────────────────────────────────
        if is_correct:
            session["correct_answers"] += 1
            session["score"]           += 10

            # mark concept learned (only for main questions)
            if not current_question.get("is_mastery_question", False):
                cid = current_question.get("concept_id")
                if cid and cid not in session["learned_concepts"]:
                    session["learned_concepts"].append(cid)
                    session["current_concept_index"] += 1
        else:
            session["incorrect_answers"] += 1
            session["score"]              = max(0, session["score"] - 5)

            # fire-and-forget mastery generation
            if not current_question.get("is_mastery_question", False):
                concept_name = current_question.get("teaching_focus", "Unknown concept")
                executor.submit(
                    _async_generate_and_insert_mastery,
                    session_id,
                    concept_name,
                    current_question
                )

        # ────────────────────────────────────────────────────────────
        # 3 — advance queue and build explanation text
        # ────────────────────────────────────────────────────────────
        queue.advance_queue()

        explanations = current_question.get("explanations", {})
        if is_correct:
            explanation_text = explanations.get("correct", "Correct!")
        else:
            wrong_expl       = explanations.get(selected_answer, "This answer is incorrect.")
            correct_expl     = explanations.get("correct", "No explanation available.")
            explanation_text = (
                f"❌ Your answer ({selected_answer}): {wrong_expl}\n\n"
                f"✅ Correct answer ({correct_answer}): {correct_expl}"
            )

        # ────────────────────────────────────────────────────────────
        # 4 — session complete?  otherwise return next pre-generated Q
        # ────────────────────────────────────────────────────────────
        progress = queue.get_progress()
        if queue.current_index >= len(queue.main_questions):
            session["completed"] = True
            logger.info("Session completed: %s", session_id)
            return jsonify({
                "session_complete": True,
                "final_score":       session["score"],
                "total_questions":   len(queue.completed_questions),
                "learned_concepts":  len(session["learned_concepts"]),
                "summary": {
                    "correct_answers":   session["correct_answers"],
                    "incorrect_answers": session["incorrect_answers"],
                    "concepts_mastered": session["learned_concepts"],
                },
                "is_correct":  is_correct,
                "explanation": explanation_text,
            })

        # get next question (instant — already pre-generated)
        try:
            next_question = get_next_progressive_question(session_id)
            if not next_question:
                session["completed"] = True
                logger.info("Session completed: %s", session_id)
                return jsonify({
                    "session_complete": True,
                    "final_score":       session["score"],
                    "total_questions":   len(queue.completed_questions),
                    "learned_concepts":  len(session["learned_concepts"]),
                    "is_correct":        is_correct,
                    "explanation":       explanation_text,
                })

            return jsonify({
                "is_correct":       is_correct,
                "explanation":      explanation_text,
                "next_question":    next_question,
                "session_complete": False,
                "progress":         progress,
                "score":            session["score"],
            })

        except Exception as e:
            logger.error("Error getting next question: %s", e)
            raise APIError("Failed to get next question", 500)

    except ValidationError as e:
        raise e
    except APIError as e:
        raise e
    except Exception as e:
        logger.error("Submit progressive answer error: %s", e)
        raise APIError(f"Failed to submit answer: {str(e)}", 500)

@app.route('/api/get-session-progress', methods=['POST'])
def get_session_progress():
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if not session_id:
            raise ValidationError('Session ID is required')
        
        if session_id not in sessions:
            raise APIError('Session not found', 404)
        
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
        
    except ValidationError as e:
        raise e
    except APIError as e:
        raise e
    except Exception as e:
        logger.error(f"Get session progress error: {e}")
        raise APIError(f'Failed to get session progress: {str(e)}', 500)

if __name__ == '__main__':
    # Ensure required environment variables are set
    if not Config.OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY environment variable is required")
        print("Please set it using: export OPENAI_API_KEY='your-api-key-here'")
        exit(1)
    
    logger.info("Starting ALP3 Progressive Learning API v4.1...")
    logger.info("Model: %s", Config.OPENAI_MODEL)
    logger.info(f"Debug mode: {Config.DEBUG}")
    logger.info(f"Active sessions will expire after {Config.SESSION_TIMEOUT_HOURS} hours")
    
    app.run(host='0.0.0.0', port=8080, debug=Config.DEBUG)