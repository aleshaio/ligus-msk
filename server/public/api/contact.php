<?php
declare(strict_types=1);
ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
try {
    require dirname(__DIR__, 2) . '/private/contact/handler.php';
    \Ligus\Contact\run();
} catch (Throwable $error) {
    // Do not log request fields, credentials or SMTP error strings.
    error_log('Ligus contact: internal failure (' . get_class($error) . ')');
    http_response_code(503);
    echo json_encode(['ok' => false, 'message' => 'Отправка временно недоступна. Позвоните нам или напишите на tender@ligus-msk.ru.'], JSON_UNESCAPED_UNICODE);
}
