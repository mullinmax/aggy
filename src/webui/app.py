from flask import Flask, render_template
import psycopg2
import os

app = Flask(__name__)

def get_db_connection():
    conn = psycopg2.connect(host=os.environ['DB_HOST'],
                            database=os.environ['DB_NAME'],
                            user=os.environ['DB_USER'],
                            password=os.environ['DB_PASS'])
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM user_data;')  # Replace 'user_data' with your table name
    user_data = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', user_data=user_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
