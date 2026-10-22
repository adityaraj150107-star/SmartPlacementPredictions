# One command starts everything (Ollama if installed + backend + website):
#     python app.py
from frontend.app import app, main

if __name__ == '__main__':
    main()
