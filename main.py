from server.web_server import app

if __name__ == "__main__":
    app.run(debug=False, port=11301, host="0.0.0.0")
