# ALP2 Installation Guide

## 🚀 **Quick Setup**

### **Prerequisites**
- Python 3.11 or higher
- pip (Python package manager)
- OpenAI API key
- Internet connection

### **Step 1: Extract Files**
```bash
# Extract the ALP2 package
unzip ALP2-Final-Package.zip
cd ALP2-Final
```

### **Step 2: Install Dependencies**
```bash
# Install required Python packages
pip install -r requirements.txt
```

### **Step 3: Configure API Key**
1. Open `app.py` in a text editor
2. Find line 14: `OPENAI_API_KEY = "your-api-key-here"`
3. Replace with your actual OpenAI API key
4. Save the file

### **Step 4: Run the Application**
```bash
# Start the Flask server
python app.py
```

### **Step 5: Access the Application**
- Open your web browser
- Go to: `http://localhost:8080`
- Start learning!

---

## 🔧 **Advanced Setup**

### **Virtual Environment (Recommended)**
```bash
# Create virtual environment
python -m venv alp2_env

# Activate virtual environment
# On Windows:
alp2_env\Scripts\activate
# On macOS/Linux:
source alp2_env/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run application
python app.py
```

### **Custom Port**
To run on a different port, edit `app.py` line 200:
```python
app.run(host='0.0.0.0', port=8080, debug=False)
```

---

## 🌐 **Deployment Options**

### **Local Network Access**
The application runs on `0.0.0.0:8080` by default, making it accessible to other devices on your local network.

### **Cloud Deployment**
ALP2 can be deployed to:
- Heroku
- Railway
- DigitalOcean
- AWS
- Google Cloud Platform

---

## 🛠 **Troubleshooting**

### **Common Issues**

**Port Already in Use**
```bash
# Find process using port 8080
lsof -i :8080
# Kill the process
kill <process_id>
```

**Missing Dependencies**
```bash
# Reinstall requirements
pip install --force-reinstall -r requirements.txt
```

**OpenAI API Errors**
- Verify your API key is correct
- Check your OpenAI account has credits
- Ensure internet connection is stable

**Permission Errors**
```bash
# On macOS/Linux, try with sudo
sudo python app.py
```

---

## 📝 **Configuration**

### **Customizable Settings in app.py**

**Session Length** (line 85):
```python
# Change base number of questions
if session['current_question_index'] >= 10:  # Change 10 to desired number
```

**Scoring System** (lines 165-170):
```python
# Modify point values
session['score'] += 10  # Points for correct answer
session['score'] -= 5   # Points for incorrect answer
```

**Compensation Ratio** (line 172):
```python
session['compensation_needed'] += 3  # Change 3 to desired ratio
```

---

## ✅ **Verification**

After installation, verify ALP2 is working:

1. **Health Check**: Visit `http://localhost:8080/api/health`
   - Should return: `{"message":"ALP2 API is running","status":"healthy"}`

2. **Frontend**: Visit `http://localhost:8080`
   - Should show the ALP2 interface

3. **Question Generation**: Enter a topic and start a quiz
   - Should generate questions within 5-10 seconds

---

## 🔒 **Security Notes**

- **API Key**: Keep your OpenAI API key secure
- **Local Use**: Default setup is for local/development use
- **Production**: For production deployment, use proper WSGI server (gunicorn, uwsgi)

---

**ALP2 is now ready to provide enhanced adaptive learning experiences!** 🎓

