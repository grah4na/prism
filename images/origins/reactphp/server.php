<?php
// PRISM echo tracer for ReactPHP (see Dockerfile).
// Emits the JSON trace described in prism/http_parse.py:decode_trace.
require '/app/http/vendor/autoload.php';

use Psr\Http\Message\ServerRequestInterface;
use React\Http\HttpServer;
use React\Http\Message\Response;
use React\Socket\SocketServer;

$server = new HttpServer(function (ServerRequestInterface $request) {
    $headers = [];
    foreach ($request->getHeaders() as $name => $values) {
        foreach ($values as $value) {
            $headers[] = [base64_encode($name), base64_encode($value)];
        }
    }
    $uri = $request->getUri();
    $path = $uri->getPath();
    if ($path === '') {
        $path = '/';
    }
    $query = $uri->getQuery();
    $trace = [
        'headers' => $headers,
        'body' => base64_encode((string) $request->getBody()),
        'version' => base64_encode($request->getProtocolVersion()),
        'uri' => base64_encode($path . ($query !== '' ? '?' . $query : '')),
        'method' => base64_encode($request->getMethod()),
    ];
    $body = json_encode($trace);
    return new Response(200, ['Content-Type' => 'application/json', 'Content-Length' => (string) strlen($body)], $body);
});

$socket = new SocketServer('0.0.0.0:80');
$server->listen($socket);
