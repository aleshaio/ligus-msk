<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require __DIR__ . '/handler.php';
umask(0077);
try {
    \Ligus\Contact\database(\Ligus\Contact\configuration());
    echo "Temporary contact state cleaned.\n";
} catch (Throwable $e) {
    fwrite(STDERR, "Contact maintenance unavailable. Run check.php.\n");
    exit(1);
}
