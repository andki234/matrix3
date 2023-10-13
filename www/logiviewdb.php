<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);

$config = require 'logiview_db_config.php';

$connect = new mysqli($config['servername'], $config['username'], $config['password'], $config['dbname']);

if ($connect->connect_error) {
    die(json_encode(["error" => "Connection error: " . $connect->connect_error]));
}

$startDate = isset($_GET['startDate']) ? $_GET['startDate'] : date('Y-m-d', strtotime('-7 days'));
$endDate = isset($_GET['endDate']) ? $_GET['endDate'] : date('Y-m-d');

$dateTimePattern = '/^\d{4}-\d{2}-\d{2}(?:\s\d{2}:\d{2}:\d{2})?$/';
if (!preg_match($dateTimePattern, $startDate) || !preg_match($dateTimePattern, $endDate)) {
    die(json_encode(["error" => "Invalid date-time format. Expected format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS."]));
}

if (strlen($startDate) == 10) {
    $startDate .= " 00:00:00";
}
if (strlen($endDate) == 10) {
    $endDate .= " 23:59:59";
}

$stmt = $connect->prepare("SELECT * FROM tempdata WHERE datetime BETWEEN ? AND ? ORDER BY datetime LIMIT 200000");
$stmt->bind_param('ss', $startDate, $endDate);
$stmt->execute();

$result = $stmt->get_result();
$data_points = array();
$n = 0;

while ($row = $result->fetch_assoc()) {
    if ($n == 1) {
        $point = array(
            "ts" => $row['datetime'],
            "t1bot" => floatval($row['T1BOT']) / 100,
            "t2bot" => floatval($row['T2BOT']) / 100,
            "t3bot" => floatval($row['T3BOT']) / 100,
            "t1mid" => floatval($row['T1MID']) / 100,
            "t2mid" => floatval($row['T2MID']) / 100,
            "t3mid" => floatval($row['T3MID']) / 100,
            "t1top" => floatval($row['T1TOP']) / 100,
            "t2top" => floatval($row['T2TOP']) / 100,
            "t3top" => floatval($row['T3TOP']) / 100,
            "tout" => floatval($row['TOUT']) / 100,
            "bp" => floatval($row['BP']) * 100,
            "pt1t2" => floatval($row['PT1T2']) * 100,
            "pt2t1" => floatval($row['PT2T1']) * 100,
        );
        array_push($data_points, $point);
        $n = 0;
    } else {
        $n++;
    }
}

if (empty($data_points)) {
    die(json_encode(["error" => "No data points generated."]));
}

header('Content-Type: application/json');
echo json_encode($data_points, JSON_NUMERIC_CHECK);

$result->free();
$connect->close();
?>
