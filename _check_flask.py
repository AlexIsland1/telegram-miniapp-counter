import os
os.environ.setdefault("DEV_MODE", "true")

from webapp.app import app

def main():
    c = app.test_client()
    r0 = c.post('/api/count', json={'user_id': 123})
    r1 = c.post('/api/click', json={'user_id': 123})
    r2 = c.post('/api/count', json={'user_id': 123})
    print('COUNT0=', r0.get_json())
    print('CLICK1=', r1.get_json())
    print('COUNT1=', r2.get_json())

if __name__ == '__main__':
    main()

