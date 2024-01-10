from flask import Flask, render_template
import psycopg2
import os

app = Flask(__name__)

def get_db_connection():
    return psycopg2.connect(host=os.environ['DB_HOST'],
                            database=os.environ['DB_NAME'],
                            user=os.environ['DB_USER'],
                            password=os.environ['DB_PASS'])

@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM your_table;')  # Replace with your query
    data = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', data=data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
