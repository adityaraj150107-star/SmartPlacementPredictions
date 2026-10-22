SMART PLACEMENT PREDICTIONS AI AGENT

QUICK START (Windows / VS Code)
1. Extract this ZIP to a normal folder, for example E:\SmartPlacementPredictions.
2. Open that folder in VS Code. It should contain app.py, backend\ and frontend\.
3. Open Terminal > New Terminal in the project root.
4. Run:
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r backend\requirements.txt
   copy backend\.env.example backend\.env
5. Open backend\.env and set a strong FLASK_SECRET_KEY and ADMIN_PASSWORD.
6. Run the app:
   python app.py
7. Open http://127.0.0.1:5000. The API is on port 8000; normally you only open port 5000.

IMPORTANT
- Real registration/password-reset OTP email requires Gmail SMTP settings in backend\.env.
- AI chat requires Ollama installed with `ollama pull llama3.2`, or a valid GEMINI_API_KEY.
- Image generation requires a valid GEMINI_API_KEY and supported model access.
- The first ML run downloads a campus-placement dataset if possible. If offline, the app creates a synthetic DEMO dataset. Scores trained on that synthetic data are for demonstration only, not real-world placement accuracy. Replace backend\data\Placement_Data_Full_Class.csv with a properly licensed, real labeled dataset for meaningful evaluation.
- This is a local academic project; do not expose it publicly without a separate security review and HTTPS deployment.

See backend\README.md for detailed setup and troubleshooting.

VISUAL ML DIAGRAMS
- The Placement Prediction page now shows a probability score ring for an individual prediction.
- Run “Find accuracy of all 4 algorithms” to render the metrics comparison chart, confusion matrices and ROC/AUC chart from the same held-out test split.
- The page also includes a prediction workflow diagram and a chart of recent saved prediction scores.
- Charts stay empty until real model evaluation/prediction data is available; they do not use made-up example scores.
