# Project Setup Guide

Follow the steps below to set up and run the project successfully.

---

## 📁 1. Clone the Repository

Clone the GitHub repository to your local machine:

```bash
git clone https://github.com/kushagrabhadauria-lab/Voice-To-Transcript.git
cd Voice-To-Transcript
```

---

## 🐍 2. Create Virtual Environment

Create a Python virtual environment named `venv`:

```bash
python3 -m venv venv
```

Activate the virtual environment:

### On Linux / macOS

```bash
source venv/bin/activate
```

### On Windows

```bash
venv\Scripts\activate
```

---

## 📦 3. Install Dependencies

Install all required packages using:

```bash
pip install -r requirements.txt
```

---

## 4. Create .env file for correct tokens and credentials

.env.sample is created to show what enviroment variable name to be used in original .env


## ▶️ 5. Run the Application

Start the script by executing:

```bash
python src.py
```

This will initiate the main processing flow of the project.

---

## 📄 Additional Notes

* Make sure your Python version matches the version required in `requirements.txt`.
* If you update dependencies, remember to regenerate the file:

```bash
pip freeze > requirements.txt
```
