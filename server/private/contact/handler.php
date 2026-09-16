<?php
declare(strict_types=1);
namespace Ligus\Contact;

use PDO;
use RuntimeException;
use PHPMailer\PHPMailer\PHPMailer;

const MAX_BODY = 12 * 1024 * 1024;
const TOKEN_TTL = 3600;
const CONSENT_VERSION = 'request-2026-09-16';

function respond(int $status, string $message, array $extra = []): never {
    http_response_code($status);
    echo json_encode(['ok' => $status === 200, 'message' => $message] + $extra, JSON_UNESCAPED_UNICODE);
    exit;
}

function configuration(): array {
    $path = getenv('LIGUS_CONFIG') ?: __DIR__ . '/config.php';
    $real = realpath($path);
    $root = realpath(PHP_SAPI === 'cli' ? dirname(__DIR__, 2) . '/public_html' : ($_SERVER['DOCUMENT_ROOT'] ?? ''));
    if (!$real || ($root && str_starts_with($real, $root . DIRECTORY_SEPARATOR))) {
        throw new RuntimeException('Private configuration required');
    }
    $c = require $real;
    if (!is_array($c) || ($c['enabled'] ?? false) !== true) {
        throw new RuntimeException('Handler disabled');
    }
    foreach (['pdo_sqlite', 'mbstring', 'fileinfo', 'openssl', 'zip'] as $extension) {
        if (!extension_loaded($extension)) throw new RuntimeException('Required PHP extension missing');
    }
    $s = $c['smtp'] ?? [];
    $test = ($c['environment'] ?? '') === 'test';
    $origin = $c['site_origin'] ?? '';
    $parts = parse_url($origin);
    $validOrigin = $parts && isset($parts['scheme'], $parts['host'])
        && !isset($parts['user']) && !isset($parts['pass']) && !isset($parts['query']) && !isset($parts['fragment'])
        && empty($parts['path']);
    if (!$validOrigin || (!$test && $parts['scheme'] !== 'https') || strlen($c['secret'] ?? '') < 32
        || !filter_var($c['recipient'] ?? '', FILTER_VALIDATE_EMAIL)
        || !filter_var($s['from_email'] ?? '', FILTER_VALIDATE_EMAIL)
        || empty($s['host']) || !is_int($s['port'] ?? null) || $s['port'] < 1 || $s['port'] > 65535
        || !in_array($s['encryption'] ?? '', ['tls', 'ssl', 'none'], true)
        || (! $test && (empty($s['username']) || empty($s['password']) || $s['encryption'] === 'none'))
        || ($test && (!in_array($s['host'], ['127.0.0.1', '::1'], true) || !in_array($parts['host'], ['127.0.0.1', 'localhost', '::1'], true)))) {
        throw new RuntimeException('Incomplete or unsafe configuration');
    }
    $c['max_file_bytes'] = min(10 * 1024 * 1024, (int)($c['max_file_bytes'] ?? 10 * 1024 * 1024));
    if ($c['max_file_bytes'] < 1) throw new RuntimeException('Invalid upload limit');
    $runtime = $c['runtime_dir'] ?? __DIR__ . '/runtime';
    if (!is_dir($runtime) && !mkdir($runtime, 0700, true)) throw new RuntimeException('Runtime unavailable');
    $c['runtime_dir'] = realpath($runtime);
    if (!$c['runtime_dir'] || ($root && str_starts_with($c['runtime_dir'] . '/', $root . '/'))) {
        throw new RuntimeException('Runtime must be private');
    }
    return $c;
}

function cleanupUploads(array $c): void {
    // Recovery after a killed PHP worker. Normal sends remove the file in finally.
    foreach (glob($c['runtime_dir'] . '/upload-*') ?: [] as $path) {
        if (is_file($path) && filemtime($path) < time() - 3600) unlink($path);
    }
}

function database(array $c): PDO {
    cleanupUploads($c);
    $db = new PDO('sqlite:' . $c['runtime_dir'] . '/state.sqlite', null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    $db->exec('PRAGMA busy_timeout=5000');
    $db->exec('CREATE TABLE IF NOT EXISTS events (at INTEGER NOT NULL, kind TEXT NOT NULL, peer TEXT NOT NULL)');
    $db->exec('CREATE INDEX IF NOT EXISTS events_lookup ON events(kind, peer, at)');
    $db->exec('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, at INTEGER NOT NULL, status TEXT NOT NULL)');
    $q = $db->prepare('DELETE FROM events WHERE at < ?'); $q->execute([time() - 3600]);
    $q = $db->prepare('DELETE FROM requests WHERE at < ?'); $q->execute([time() - 7200]);
    return $db;
}

function throttle(PDO $db, string $kind, string $peer, int $limit, int $globalLimit): void {
    $db->exec('BEGIN IMMEDIATE');
    try {
        $q = $db->prepare('SELECT COUNT(*) FROM events WHERE kind = ? AND peer = ? AND at > ?');
        $q->execute([$kind, $peer, time() - 600]);
        $n = (int)$q->fetchColumn();
        $q = $db->prepare('SELECT COUNT(*) FROM events WHERE kind = ? AND at > ?');
        $q->execute([$kind, time() - 3600]);
        $global = (int)$q->fetchColumn();
        if ($n >= $limit || $global >= $globalLimit) {
            $db->exec('ROLLBACK');
            header('Retry-After: 600');
            respond(429, 'Слишком много попыток. Повторите через 10 минут или свяжитесь с нами по телефону.');
        }
        $q = $db->prepare('INSERT INTO events VALUES (?, ?, ?)'); $q->execute([time(), $kind, $peer]);
        $db->exec('COMMIT');
    } catch (\Throwable $e) {
        if ($db->inTransaction()) $db->rollBack();
        throw $e;
    }
}

function field(string $name, int $max, bool $required = false): string {
    $value = $_POST[$name] ?? '';
    if (!is_string($value) || !mb_check_encoding($value, 'UTF-8') || str_contains($value, "\0")) {
        respond(422, 'Проверьте заполнение поля.', ['field' => $name]);
    }
    $value = trim($value);
    if (($required && $value === '') || mb_strlen($value, 'UTF-8') > $max) {
        respond(422, 'Заполните поле и проверьте длину текста.', ['field' => $name]);
    }
    return $value;
}

function attachment(array $c): ?array {
    if (array_diff(array_keys($_FILES), ['attachment'])) respond(422, 'Выберите один файл.');
    if (!isset($_FILES['attachment'])) return null;
    $f = $_FILES['attachment'];
    if (!is_array($f) || !is_int($f['error'] ?? null)) respond(422, 'Выберите один файл.', ['field' => 'attachment']);
    if ($f['error'] === UPLOAD_ERR_NO_FILE) return null;
    if ($f['error'] === UPLOAD_ERR_INI_SIZE || $f['error'] === UPLOAD_ERR_FORM_SIZE) respond(413, 'Файл больше допустимого размера: 10 МБ.');
    if ($f['error'] !== UPLOAD_ERR_OK || !is_uploaded_file($f['tmp_name'])) respond(422, 'Не удалось загрузить файл. Выберите его заново.');
    $size = filesize($f['tmp_name']);
    if ($size === false || $size === 0 || $size > $c['max_file_bytes']) respond(413, 'Выберите непустой файл размером до 10 МБ.');
    $name = basename(str_replace('\\', '/', (string)$f['name']));
    if (!mb_check_encoding($name, 'UTF-8')) respond(422, 'Переименуйте файл и загрузите его заново.');
    $name = preg_replace('/[\x00-\x1f\x7f]/u', '', $name);
    $ext = strtolower(pathinfo($name, PATHINFO_EXTENSION));
    $types = ['pdf' => 'application/pdf', 'doc' => 'application/msword', 'xls' => 'application/vnd.ms-excel',
        'docx' => 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'xlsx' => 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'txt' => 'text/plain', 'csv' => 'text/csv'];
    $mime = (new \finfo(FILEINFO_MIME_TYPE))->file($f['tmp_name']);
    $start = file_get_contents($f['tmp_name'], false, null, 0, 1024);
    $valid = isset($types[$ext]);
    if ($ext === 'pdf') $valid = $mime === 'application/pdf' && str_starts_with($start, '%PDF-');
    if (in_array($ext, ['txt', 'csv'], true)) {
        $content = file_get_contents($f['tmp_name']);
        $valid = in_array($mime, ['text/plain', 'text/csv', 'application/csv'], true) && !str_contains($content, "\0");
    }
    if (in_array($ext, ['doc', 'xls'], true)) {
        $valid = str_starts_with($start, "\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
            && in_array($mime, ['application/msword', 'application/vnd.ms-excel', 'application/x-ole-storage', 'application/CDFV2', 'application/octet-stream'], true);
    }
    if (in_array($ext, ['docx', 'xlsx'], true)) {
        $zip = new \ZipArchive();
        $valid = false;
        if ($zip->open($f['tmp_name']) === true) {
            $valid = $zip->numFiles <= 2000 && $zip->locateName('[Content_Types].xml') !== false
                && $zip->locateName($ext === 'docx' ? 'word/document.xml' : 'xl/workbook.xml') !== false;
            $expanded = 0;
            for ($i = 0; $i < $zip->numFiles && $valid; $i++) {
                $stat = $zip->statIndex($i);
                $expanded += $stat['size'];
                if ($expanded > 64 * 1024 * 1024 || str_ends_with(strtolower($stat['name']), 'vbaproject.bin')) $valid = false;
            }
            $zip->close();
        }
    }
    if (!$valid) respond(422, 'Формат или содержимое файла не поддерживается. Выберите PDF, DOC, DOCX, XLS, XLSX, CSV или TXT.', ['field' => 'attachment']);
    return ['tmp' => $f['tmp_name'], 'name' => mb_substr(pathinfo($name, PATHINFO_FILENAME), 0, 120) . '.' . $ext, 'mime' => $types[$ext]];
}

function run(): void {
    umask(0077);
    $method = $_SERVER['REQUEST_METHOD'] ?? '';
    if (!in_array($method, ['GET', 'POST'], true)) { header('Allow: GET, POST'); respond(405, 'Метод не поддерживается.'); }
    if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > MAX_BODY) respond(413, 'Размер запроса превышает лимит. Прикрепите файл до 10 МБ.');
    $c = configuration();
    $origin = $_SERVER['HTTP_ORIGIN'] ?? '';
    if ($origin === '' && isset($_SERVER['HTTP_REFERER'])) {
        $u = parse_url($_SERVER['HTTP_REFERER']);
        if ($u && isset($u['scheme'], $u['host'])) $origin = $u['scheme'] . '://' . $u['host'] . (isset($u['port']) ? ':' . $u['port'] : '');
    }
    if ($origin !== $c['site_origin']) respond(403, 'Откройте форму на сайте «Лигус» и повторите отправку.');
    $peer = hash_hmac('sha256', $_SERVER['REMOTE_ADDR'] ?? '', $c['secret']);
    $db = database($c);
    if ($method === 'GET') {
        throttle($db, 'token', $peer, 30, 1000);
        $payload = time() . '.' . bin2hex(random_bytes(16));
        respond(200, '', ['token' => $payload . '.' . hash_hmac('sha256', $payload . '.' . $peer, $c['secret'])]);
    }
    $token = field('token', 160, true);
    $parts = explode('.', $token);
    if (count($parts) !== 3 || !ctype_digit($parts[0]) || !preg_match('/^[a-f0-9]{32}$/D', $parts[1])
        || !hash_equals(hash_hmac('sha256', $parts[0] . '.' . $parts[1] . '.' . $peer, $c['secret']), $parts[2])
        || (int)$parts[0] > time() || time() - (int)$parts[0] > TOKEN_TTL) {
        respond(403, 'Срок действия формы истёк. Повторите отправку.', ['code' => 'token_expired']);
    }
    $id = $parts[1];
    $q = $db->prepare('SELECT status FROM requests WHERE id = ?'); $q->execute([$id]);
    $previous = $q->fetchColumn();
    if ($previous === 'sent') respond(200, 'Заявка передана почтовому серверу.', ['requestId' => $id]);
    if ($previous) respond(409, 'Отправка уже выполнялась. Если подтверждения нет, свяжитесь с нами по телефону или почте.', ['requestId' => $id]);
    throttle($db, 'submit', $peer, 5, 120);
    if (field('_honey', 1000) !== '') respond(422, 'Не удалось отправить заявку. Свяжитесь с нами по телефону.');
    $name = field('name', 100, true);
    $phone = field('phone', 30, true);
    $organization = field('organization', 200);
    $email = field('email', 200);
    $comment = field('comment', 5000);
    $digits = preg_replace('/\D/', '', $phone);
    if (strlen($digits) < 10 || strlen($digits) > 15) respond(422, 'Укажите телефон: от 10 до 15 цифр.', ['field' => 'phone']);
    if ($email !== '' && (!filter_var($email, FILTER_VALIDATE_EMAIL) || preg_match('/[\r\n]/', $email))) respond(422, 'Проверьте адрес электронной почты.', ['field' => 'email']);
    if (field('consent', 8, true) !== 'on') respond(422, 'Подтвердите согласие на обработку данных.', ['field' => 'consent']);
    $file = attachment($c);
    $q = $db->prepare("INSERT OR IGNORE INTO requests VALUES (?, ?, 'sending')"); $q->execute([$id, time()]);
    if (!$q->rowCount()) respond(409, 'Заявка уже обрабатывается.');
    $temp = null;
    $sent = false;
    try {
        require_once __DIR__ . '/vendor/phpmailer/src/Exception.php';
        require_once __DIR__ . '/vendor/phpmailer/src/PHPMailer.php';
        require_once __DIR__ . '/vendor/phpmailer/src/SMTP.php';
        $mail = new PHPMailer(true);
        $s = $c['smtp'];
        $mail->isSMTP();
        $mail->Host = $s['host'];
        $mail->Port = $s['port'];
        $mail->SMTPAuth = ($s['username'] ?? '') !== '';
        $mail->Username = $s['username'];
        $mail->Password = $s['password'];
        $mail->SMTPSecure = $s['encryption'] === 'none' ? '' : $s['encryption'];
        $mail->SMTPAutoTLS = $s['encryption'] !== 'none';
        $mail->Timeout = 15;
        $mail->getSMTPInstance()->Timelimit = 25;
        $mail->CharSet = PHPMailer::CHARSET_UTF8;
        $mail->setFrom($s['from_email'], $s['from_name'] ?? 'Лигус');
        $mail->addAddress($c['recipient']);
        if ($email !== '') $mail->addReplyTo($email);
        $mail->Subject = 'Лигус — заявка ' . substr($id, 0, 8);
        $mail->MessageID = '<' . $id . '@' . parse_url($c['site_origin'], PHP_URL_HOST) . '>';
        $mail->Body = "Новая заявка с сайта «Лигус»\n\nИмя: $name\nТелефон: $phone\nОрганизация: $organization\nEmail: $email\n\nЗадача:\n$comment\n\nID: $id\nВремя UTC: " . gmdate('c') . "\nСогласие: отмечено в форме\nВерсия текста: " . CONSENT_VERSION;
        if ($file) {
            $temp = $c['runtime_dir'] . '/upload-' . bin2hex(random_bytes(16));
            if (!move_uploaded_file($file['tmp'], $temp)) throw new RuntimeException('Upload move failed');
            $mail->addAttachment($temp, $file['name'], PHPMailer::ENCODING_BASE64, $file['mime']);
        }
        $sent = $mail->send();
    } catch (\Throwable $e) {
        error_log('Ligus contact: SMTP failed; request=' . $id);
    } finally {
        if ($temp !== null && is_file($temp)) unlink($temp);
        $q = $db->prepare('UPDATE requests SET status = ? WHERE id = ?');
        $q->execute([$sent ? 'sent' : 'uncertain', $id]);
    }
    if (!$sent) respond(502, 'Не удалось подтвердить отправку. Данные остались в форме. Свяжитесь с нами по телефону или напишите на tender@ligus-msk.ru.', ['requestId' => $id]);
    respond(200, 'Заявка передана почтовому серверу.', ['requestId' => $id]);
}
