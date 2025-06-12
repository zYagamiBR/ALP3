// ALP3 - Progressive Learning Platform JavaScript

// API configuration
const API_BASE_URL = window.location.origin + '/api';

// Global state management
class ALP3State {
    constructor() {
        this.sessionId = null;
        this.currentQuestion = null;
        this.selectedAnswer = null;
        this.score = 100;
        this.progress = {
            current_question: 0,
            total_questions: 0,
            completed: 0,
            remaining: 0,
            progress_percentage: 0
        };
        this.conceptsLearned = 0;
        this.sessionComplete = false;
        this.isLoading = false;
    }

    reset() {
        this.sessionId = null;
        this.currentQuestion = null;
        this.selectedAnswer = null;
        this.score = 100;
        this.progress = {
            current_question: 0,
            total_questions: 0,
            completed: 0,
            remaining: 0,
            progress_percentage: 0
        };
        this.conceptsLearned = 0;
        this.sessionComplete = false;
        this.isLoading = false;
    }
}

const state = new ALP3State();

// UI Management
class UIManager {
    static showScreen(screenId) {
        // Hide all screens
        document.querySelectorAll('.screen').forEach(screen => {
            screen.classList.remove('active');
        });
        
        // Show target screen
        const targetScreen = document.getElementById(screenId);
        if (targetScreen) {
            targetScreen.classList.add('active');
        }
    }

    static showLoading(message = 'Creating your progressive learning plan...') {
        document.getElementById('loading-message').textContent = message;
        this.showScreen('loading-screen');
        this.animateLoadingSteps();
    }

    static animateLoadingSteps() {
        const steps = document.querySelectorAll('.loading-steps .step');
        let currentStep = 0;

        const interval = setInterval(() => {
            if (currentStep < steps.length) {
                steps[currentStep].classList.add('active');
                currentStep++;
            } else {
                clearInterval(interval);
            }
        }, 1500);
    }

    static updateProgress() {
        const progressBar = document.getElementById('progress-bar');
        const progressText = document.getElementById('progress-text');
        const scoreElement = document.getElementById('current-score');
        const conceptProgress = document.getElementById('concept-progress');

        if (progressBar && state.progress.total_questions > 0) {
            const percentage = (state.progress.completed / state.progress.total_questions) * 100;
            progressBar.style.width = `${percentage}%`;
        }

        if (progressText) {
            progressText.textContent = `Question ${state.progress.current_question} of ${state.progress.total_questions}`;
        }

        if (scoreElement) {
            scoreElement.textContent = `Score: ${state.score}`;
        }

        if (conceptProgress) {
            conceptProgress.textContent = `Concepts Learned: ${state.conceptsLearned}`;
        }
    }

    static displayQuestion(questionData) {
        const questionText = document.getElementById('question-text');
        const optionsContainer = document.getElementById('options-container');
        const questionDifficulty = document.getElementById('question-difficulty');
        const questionConcept = document.getElementById('question-concept');
        const questionType = document.getElementById('question-type');

        // Update question text
        if (questionText) {
            questionText.textContent = questionData.question;
        }

        // Update question metadata
        if (questionDifficulty) {
            questionDifficulty.textContent = questionData.difficulty || 'Medium';
            questionDifficulty.className = `difficulty ${questionData.difficulty || 'medium'}`;
        }

        if (questionConcept) {
            questionConcept.textContent = `Concept: ${questionData.teaching_focus || 'Learning Concept'}`;
        }

        // Update question type indicator
        if (questionType) {
            const isMastery = questionData.is_mastery_question;
            questionType.innerHTML = isMastery 
                ? '<span class="mastery-indicator">🎯 Mastery Check</span>'
                : '<span class="teaching-indicator">🎓 Teaching Question</span>';
        }

        // Generate options
        if (optionsContainer && questionData.options) {
            optionsContainer.innerHTML = '';
            
            Object.entries(questionData.options).forEach(([key, value]) => {
                const optionElement = document.createElement('div');
                optionElement.className = 'option';
                optionElement.innerHTML = `
                    <input type="radio" id="option-${key}" name="answer" value="${key}">
                    <label for="option-${key}">
                        <span class="option-letter">${key}</span>
                        <span class="option-text">${value}</span>
                    </label>
                `;
                optionsContainer.appendChild(optionElement);
            });

            // Add event listeners for option selection
            optionsContainer.addEventListener('change', (e) => {
                if (e.target.type === 'radio') {
                    state.selectedAnswer = e.target.value;
                    document.getElementById('submit-btn').disabled = false;
                }
            });
        }

        // Update progress
        if (questionData.progress) {
            state.progress = questionData.progress;
        }
        state.score = questionData.score || state.score;
        this.updateProgress();

        // Show quiz screen
        this.showScreen('quiz-screen');
        
        // Hide results and enable submit
        document.getElementById('results-container').classList.add('hidden');
        document.getElementById('submit-btn').disabled = true;
        state.selectedAnswer = null;
    }

    static displayResults(resultData) {
        const resultsContainer = document.getElementById('results-container');
        const resultStatus = document.getElementById('result-status');
        const scoreChange = document.getElementById('score-change');
        const explanationContent = document.getElementById('explanation-content');
        const learningProgress = document.getElementById('learning-progress');

        // Show results container
        resultsContainer.classList.remove('hidden');

        // Update result status
        if (resultStatus) {
            const isCorrect = resultData.is_correct;
            resultStatus.innerHTML = isCorrect 
                ? '<span class="correct">✅ Correct!</span>'
                : '<span class="incorrect">❌ Incorrect</span>';
        }

        // Update score change
        if (scoreChange) {
            const change = resultData.is_correct ? '+10' : '-5';
            const changeClass = resultData.is_correct ? 'positive' : 'negative';
            scoreChange.innerHTML = `<span class="${changeClass}">${change} points</span>`;
        }

        // Update explanation
        if (explanationContent && resultData.explanation) {
            explanationContent.innerHTML = this.formatExplanation(resultData.explanation);
        }

        // Update learning progress
        if (learningProgress) {
            let progressHTML = '';
            
            if (resultData.is_correct) {
                progressHTML = '<div class="progress-update success">🎉 Great job! Moving to the next concept...</div>';
            } else {
                progressHTML = '<div class="progress-update mastery">🎯 Added mastery questions to help you learn this concept better</div>';
            }
            
            learningProgress.innerHTML = progressHTML;
        }

        // Update state
        state.score = resultData.score || state.score;
        if (resultData.progress) {
            state.progress = resultData.progress;
        }
        this.updateProgress();

        // Handle session completion
        if (resultData.session_complete) {
            setTimeout(() => {
                this.showSessionComplete(resultData);
            }, 3000);
        }
    }

    static formatExplanation(explanation) {
        // Enhanced explanation formatting
        if (explanation.includes('❌') && explanation.includes('✅')) {
            // Multi-part explanation (wrong + correct)
            const parts = explanation.split('\n\n');
            return parts.map(part => {
                if (part.includes('❌')) {
                    return `<div class="explanation-wrong">${part}</div>`;
                } else if (part.includes('✅')) {
                    return `<div class="explanation-correct">${part}</div>`;
                } else {
                    return `<div class="explanation-general">${part}</div>`;
                }
            }).join('');
        } else {
            // Single explanation
            return `<div class="explanation-general">${explanation}</div>`;
        }
    }

    static showSessionComplete(resultData) {
        const sessionComplete = document.getElementById('session-complete');
        const finalScore = document.getElementById('final-score');
        const totalQuestions = document.getElementById('total-questions');
        const conceptsMastered = document.getElementById('concepts-mastered');
        const accuracyRate = document.getElementById('accuracy-rate');

        // Update completion data
        if (finalScore) {
            finalScore.textContent = `Final Score: ${resultData.final_score || state.score}`;
        }

        if (totalQuestions) {
            totalQuestions.textContent = resultData.total_questions || state.progress.completed;
        }

        if (conceptsMastered) {
            conceptsMastered.textContent = resultData.learned_concepts || state.conceptsLearned;
        }

        if (accuracyRate && resultData.summary) {
            const total = resultData.summary.correct_answers + resultData.summary.incorrect_answers;
            const accuracy = total > 0 ? Math.round((resultData.summary.correct_answers / total) * 100) : 0;
            accuracyRate.textContent = `${accuracy}%`;
        }

        // Show completion screen
        sessionComplete.classList.remove('hidden');
        state.sessionComplete = true;
    }

    static showError(message) {
        alert(`Error: ${message}`);
        // In a production app, you'd want a more elegant error display
    }
}

// API Communication
class APIClient {
    static async startProgressiveSession(type, data) {
        try {
            const response = await fetch(`${API_BASE_URL}/start-progressive-session`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    type: type,
                    ...data
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Start session error:', error);
            throw error;
        }
    }

    static async submitAnswer(sessionId, selectedAnswer, currentQuestion) {
        try {
            const response = await fetch(`${API_BASE_URL}/submit-progressive-answer`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: sessionId,
                    selected_answer: selectedAnswer,
                    current_question: currentQuestion
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Submit answer error:', error);
            throw error;
        }
    }
}

// Event Handlers
async function startTopicSession() {
    const topicInput = document.getElementById('topic-input');
    const topic = topicInput.value.trim();

    if (!topic) {
        UIManager.showError('Please enter a topic to learn about');
        return;
    }

    try {
        state.isLoading = true;
        UIManager.showLoading('Creating your progressive learning plan...');

        const questionData = await APIClient.startProgressiveSession('topic', { topic });
        
        state.sessionId = questionData.session_id;
        state.currentQuestion = questionData;
        
        UIManager.displayQuestion(questionData);
    } catch (error) {
        UIManager.showError(`Failed to start session: ${error.message}`);
        UIManager.showScreen('start-screen');
    } finally {
        state.isLoading = false;
    }
}

async function submitAnswer() {
    if (!state.selectedAnswer || !state.sessionId || !state.currentQuestion) {
        return;
    }

    try {
        const submitBtn = document.getElementById('submit-btn');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Processing...';

        const resultData = await APIClient.submitAnswer(
            state.sessionId,
            state.selectedAnswer,
            state.currentQuestion
        );

        UIManager.displayResults(resultData);

        // Store next question if available
        if (resultData.next_question) {
            state.currentQuestion = resultData.next_question;
        }

    } catch (error) {
        UIManager.showError(`Failed to submit answer: ${error.message}`);
    } finally {
        const submitBtn = document.getElementById('submit-btn');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit Answer';
    }
}

function continueToNextQuestion() {
    if (state.currentQuestion && !state.sessionComplete) {
        UIManager.displayQuestion(state.currentQuestion);
    }
}

function restartSession() {
    state.reset();
    UIManager.showScreen('start-screen');
    
    // Reset form
    document.getElementById('topic-input').value = '';
    document.getElementById('file-input').value = '';
}

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    // Event listeners
    document.getElementById('start-topic-btn').addEventListener('click', startTopicSession);
    document.getElementById('submit-btn').addEventListener('click', submitAnswer);
    document.getElementById('next-btn').addEventListener('click', continueToNextQuestion);
    document.getElementById('restart-btn').addEventListener('click', restartSession);

    // Enter key support for topic input
    document.getElementById('topic-input').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            startTopicSession();
        }
    });

    // File input handling (placeholder for future implementation)
    document.getElementById('file-input').addEventListener('change', function(e) {
        const startFileBtn = document.getElementById('start-file-btn');
        startFileBtn.disabled = !e.target.files.length;
    });

    console.log('ALP3 Progressive Learning Platform initialized');
});

