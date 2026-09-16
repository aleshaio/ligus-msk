<?php
// Copy to config.php OUTSIDE public_html. Never commit real credentials.
return [
    'enabled' => false,
    'environment' => 'production',
    'site_origin' => 'https://ligus-msk.ru',
    // Generate: php -r 'echo bin2hex(random_bytes(32)), PHP_EOL;'
    'secret' => '',
    'recipient' => 'tender@ligus-msk.ru',
    'smtp' => [
        'host' => '',
        'port' => 587,
        'encryption' => 'tls', // tls = STARTTLS (587), ssl = implicit TLS (465)
        'username' => '',
        'password' => '',
        'from_email' => '', // Address allowed by your SMTP provider
        'from_name' => 'Лигус',
    ],
    // Technical state contains hashes/timestamps/status, never form contents.
    'runtime_dir' => __DIR__ . '/runtime',
    'max_file_bytes' => 10 * 1024 * 1024,
];
