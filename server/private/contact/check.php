<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require __DIR__ . '/handler.php';
umask(0077);
try {
    $c = \Ligus\Contact\configuration();
    \Ligus\Contact\database($c);
    echo "OK: configuration, PHP extensions and private storage. SMTP delivery not tested.\n";
} catch (Throwable $e) {
    fwrite(STDERR, "NOT READY: " . $e->getMessage() . "\n");
    exit(1);
}
