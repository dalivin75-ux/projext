import os
from io import BytesIO

import pytest

os.environ['TESTING'] = '1'

from treasure import app


@pytest.fixture()
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    test_db = os.path.join(os.path.dirname(__file__), '..', 'test_treasure.db')
    if os.path.exists(test_db):
        os.remove(test_db)
    app.config['DATABASE'] = test_db
    with app.app_context():
        from treasure import init_db
        init_db()
    with app.test_client() as client:
        yield client
    if os.path.exists(test_db):
        os.remove(test_db)


def test_homepage_has_swedish_title(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'Skattjaktens hamn' in response.data.lower() or b'skattjaktens hamn' in response.data.lower()


def test_member_registration_and_login(client):
    response = client.post('/register', data={
        'username': 'pirat42',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Konto skapat' in response.data or b'konto skapat' in response.data

    login_response = client.post('/login', data={
        'username': 'pirat42',
        'password': 'hemligt123'
    }, follow_redirects=True)
    assert login_response.status_code == 200
    assert b'Logga ut' in login_response.data or b'logga ut' in login_response.data


def test_admin_can_publish_submission(client):
    client.post('/register', data={
        'username': 'adminpirat',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'adminpirat',
        'password': 'hemligt123'
    }, follow_redirects=True)

    response = client.post('/dashboard/create', data={
        'title': 'Guld i klippskrevan',
        'summary': 'En skatt i den gamla gruvan.',
        'content': 'Svarta flaggan hide the chest in the stone ruins.',
        'image_url': 'https://example.com/treasure.jpg',
        'location': 'Sjövik',
        'difficulty': 'Medel',
        'verification_code': 'GULD-42'
    }, follow_redirects=True)
    assert response.status_code == 200

    client.get('/logout')
    client.post('/login', data={
        'username': 'adminpirat',
        'password': 'hemligt123'
    }, follow_redirects=True)

    admin_response = client.post('/admin/publish/1', follow_redirects=True)
    assert admin_response.status_code == 200


def test_member_can_upload_valid_image(client):
    client.post('/register', data={
        'username': 'bildpirat',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'bildpirat',
        'password': 'hemligt123'
    }, follow_redirects=True)

    response = client.post('/dashboard/create', data={
        'title': 'Bildskatten',
        'summary': 'Ett test med riktig bild.',
        'content': 'Skatten finns vid fyren.',
        'location': 'Fyren',
        'difficulty': 'Lätt',
        'verification_code': 'FYR-7',
        'image_file': (BytesIO(b'fake-png-data'), 'skatt.png')
    }, content_type='multipart/form-data', follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        from treasure import get_db
        hunt = get_db().execute("SELECT image_url FROM hunts WHERE title = ?", ('Bildskatten',)).fetchone()
        assert hunt["image_url"].startswith('/uploads/')


def test_member_cannot_upload_unsupported_image(client):
    client.post('/register', data={
        'username': 'fildetektiv',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'fildetektiv',
        'password': 'hemligt123'
    }, follow_redirects=True)

    response = client.post('/dashboard/create', data={
        'title': 'Farlig fil',
        'summary': 'Ska inte sparas.',
        'content': 'Innehåll.',
        'verification_code': 'FARLIG-1',
        'image_file': (BytesIO(b'not-an-image'), 'skatt.exe')
    }, content_type='multipart/form-data', follow_redirects=True)

    assert response.status_code == 200
    assert b'JPG, PNG eller WebP' in response.data


def test_member_can_edit_and_resubmit_own_rejected_hunt(client):
    client.post('/register', data={
        'username': 'redigerare',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'redigerare',
        'password': 'hemligt123'
    }, follow_redirects=True)

    client.post('/dashboard/create', data={
        'title': 'Gammal titel',
        'summary': 'Gammal sammanfattning.',
        'content': 'Gammal ledtråd.',
        'location': 'Ön',
        'difficulty': 'Medel',
        'verification_code': 'GAMMAL-1'
    }, follow_redirects=True)

    with app.app_context():
        from treasure import get_db
        hunt = get_db().execute("SELECT id FROM hunts LIMIT 1").fetchone()
        hunt_id = hunt["id"]
        get_db().execute("UPDATE hunts SET status = 'rejected' WHERE id = ?", (hunt_id,))
        get_db().commit()

    response = client.post(f'/dashboard/edit/{hunt_id}', data={
        'title': 'Ny titel',
        'summary': 'Förbättrad sammanfattning.',
        'content': 'Ny tydlig ledtråd.',
        'image_url': 'https://example.com/ny-skatt.jpg',
        'location': 'Den gröna ön',
        'difficulty': 'Svår',
        'verification_code': 'NY-42'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'granskning' in response.data.lower()
    with app.app_context():
        from treasure import get_db
        updated = get_db().execute("SELECT * FROM hunts WHERE id = ?", (hunt_id,)).fetchone()
        assert updated["title"] == 'Ny titel'
        assert updated["status"] == 'pending'


def test_member_cannot_edit_another_members_hunt(client):
    client.post('/register', data={
        'username': 'forsta',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'forsta',
        'password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/dashboard/create', data={
        'title': 'Första skatt',
        'summary': 'Ägs av första.',
        'content': 'Ledtråd.',
        'verification_code': 'FORSTA-1',
    }, follow_redirects=True)
    client.get('/logout')

    client.post('/register', data={
        'username': 'andra',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'andra',
        'password': 'hemligt123'
    }, follow_redirects=True)

    response = client.post('/dashboard/edit/1', data={
        'title': 'Försök till kapning',
        'summary': 'Inte tillåtet.',
        'content': 'Inte tillåtet.'
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        from treasure import get_db
        hunt = get_db().execute("SELECT title FROM hunts WHERE id = 1").fetchone()
        assert hunt["title"] == 'Första skatt'


def test_admin_moderation_actions_create_audit_log(client):
    client.post('/register', data={
        'username': 'loggadmin',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'loggadmin',
        'password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/dashboard/create', data={
        'title': 'Loggad skatt',
        'summary': 'Ska få ett beslut.',
        'content': 'En ledtråd.',
        'verification_code': 'LOGG-1',
    }, follow_redirects=True)

    publish_response = client.post('/admin/publish/1', follow_redirects=True)
    assert publish_response.status_code == 200

    client.post('/dashboard/create', data={
        'title': 'Avvisad skatt',
        'summary': 'Ska avvisas.',
        'content': 'En annan ledtråd.',
        'verification_code': 'AVVISA-1',
    }, follow_redirects=True)
    reject_response = client.post('/admin/reject/2', follow_redirects=True)
    assert reject_response.status_code == 200

    with app.app_context():
        from treasure import get_db
        logs = get_db().execute(
            "SELECT action, actor_username FROM moderation_logs ORDER BY id"
        ).fetchall()
        assert [(row["action"], row["actor_username"]) for row in logs] == [
            ('published', 'loggadmin'),
            ('rejected', 'loggadmin'),
        ]

    history_response = client.get('/admin/moderation-log')
    assert history_response.status_code == 200
    assert b'Loggad skatt' in history_response.data
    assert b'Avvisad skatt' in history_response.data


def test_ensure_admin_exists_for_first_user(client):
    with app.app_context():
        from treasure import get_db
        db = get_db()
        db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                   ('sjoman', 'hash', 'member'))
        db.commit()

    from treasure import ensure_admin_exists
    with app.app_context():
        ensure_admin_exists()

    with app.app_context():
        from treasure import get_db
        row = get_db().execute("SELECT role FROM users WHERE username = ?", ('sjoman',)).fetchone()
        assert row["role"] == "admin"


def test_admin_can_manage_user_roles(client):
    client.post('/register', data={
        'username': 'adminpirat',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/register', data={
        'username': 'medlem',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)

    client.post('/login', data={
        'username': 'adminpirat',
        'password': 'hemligt123'
    }, follow_redirects=True)

    response = client.post('/admin/users/role/2', data={
        'role': 'moderator'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'moderator' in response.data.lower()


def test_member_can_verify_treasure_and_archive_finding(client):
    client.post('/register', data={
        'username': 'skapare',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'skapare',
        'password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/dashboard/create', data={
        'title': 'Den hemliga kistan',
        'summary': 'En skatt med verifieringskod.',
        'content': 'Följ kompassen till fyren.',
        'verification_code': 'GULD-42',
        'verification_code': 'GULD-42',
    }, follow_redirects=True)

    client.post('/admin/publish/1', follow_redirects=True)
    client.post('/logout')
    client.post('/register', data={
        'username': 'finnare',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'finnare',
        'password': 'hemligt123'
    }, follow_redirects=True)

    response = client.post('/treasure/1/claim', data={
        'verification_code': 'guld-42'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'Hittad!' in response.data
    assert b'finnare' in response.data
    with app.app_context():
        from treasure import get_db
        hunt = get_db().execute("SELECT * FROM hunts WHERE id = 1").fetchone()
        assert hunt["status"] == 'found'
        assert hunt["found_by_username"] == 'finnare'
        assert hunt["duration_seconds"] is not None
        assert hunt["found_at"] is not None


def test_wrong_verification_code_does_not_archive_treasure(client):
    client.post('/register', data={
        'username': 'skapare',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'skapare',
        'password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/dashboard/create', data={
        'title': 'Koden vaktar',
        'summary': 'Fel kod ska inte räcka.',
        'content': 'Vid det gamla trädet.',
        'verification_code': 'RATT-KOD',
        'verification_code': 'RATT-KOD',
    }, follow_redirects=True)
    client.post('/admin/publish/1', follow_redirects=True)

    response = client.post('/treasure/1/claim', data={
        'verification_code': 'FEL-KOD'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'Fel verifieringskod' in response.data
    with app.app_context():
        from treasure import get_db
        hunt = get_db().execute("SELECT status, found_by_username FROM hunts WHERE id = 1").fetchone()
        assert hunt["status"] == 'published'
        assert hunt["found_by_username"] is None


def test_treasure_hunt_requires_verification_code(client):
    client.post('/register', data={
        'username': 'utan-kod',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'utan-kod',
        'password': 'hemligt123'
    }, follow_redirects=True)

    response = client.post('/dashboard/create', data={
        'title': 'Saknar kod',
        'summary': 'Ska inte skapas.',
        'content': 'Ingen kod angiven.'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'verifieringskod m' in response.data.lower()
    with app.app_context():
        from treasure import get_db
        hunt = get_db().execute("SELECT id FROM hunts WHERE title = ?", ('Saknar kod',)).fetchone()
        assert hunt is None


def test_owner_can_edit_published_treasure_and_resubmit(client):
    client.post('/register', data={
        'username': 'skapare',
        'password': 'hemligt123',
        'confirm_password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'skapare',
        'password': 'hemligt123'
    }, follow_redirects=True)
    client.post('/dashboard/create', data={
        'title': 'Publicerad skatt',
        'summary': 'Originaltext.',
        'content': 'Originalledtråd.',
        'verification_code': 'ORIGINAL-1'
    }, follow_redirects=True)
    client.post('/admin/publish/1', follow_redirects=True)

    response = client.post('/dashboard/edit/1', data={
        'title': 'Uppdaterad skatt',
        'summary': 'Ny text.',
        'content': 'Ny ledtråd.',
        'verification_code': 'NY-1'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'skickats till granskning' in response.data.lower()
    with app.app_context():
        from treasure import get_db
        hunt = get_db().execute("SELECT title, status FROM hunts WHERE id = 1").fetchone()
        assert hunt["title"] == 'Uppdaterad skatt'
        assert hunt["status"] == 'pending'
