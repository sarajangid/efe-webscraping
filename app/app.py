from flask import Flask, jsonify
from scraper import run_scraper

app = Flask(__name__)

@app.route("/run-scraper", methods=["GET"])
def trigger_scraper():
    result = run_scraper()
    return jsonify({"result": result})

if __name__ == "__main__":
    app.run(debug=True)