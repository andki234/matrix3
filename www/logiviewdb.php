<?php

// Enable error reporting for debugging
error_reporting(E_ALL);
ini_set('display_errors', 1);

// Import database connection credentials
$config = require 'logiview_db_config.php';

// Create a database connection
$connect = new mysqli($config['servername'], $config['username'], $config['password'], $config['dbname']);

// Check connection status
if ($connect->connect_error) {
    die("Connection error: " . $connect->connect_error);
}

// Fetch and sanitize input parameters
$startDate = isset($_GET['startDate']) ? $_GET['startDate'] : date('Y-m-d', strtotime('-7 days'));
$endDate = isset($_GET['endDate']) ? $_GET['endDate'] : date('Y-m-d');

// Validate date format
if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $startDate) || !preg_match('/^\d{4}-\d{2}-\d{2}$/', $endDate)) {
    die("Invalid date format. Expected format: YYYY-MM-DD.");
}

// Prepare and execute the query with parameterized inputs
$stmt = $connect->prepare("SELECT * FROM tempdata WHERE datetime BETWEEN ? AND ? ORDER BY datetime LIMIT 200000");
$stmt->bind_param('ss', $startDate, $endDate);
$stmt->execute();

$result = $stmt->get_result();

$data_points = array();
$n = 0;

while ($row = $result->fetch_assoc()) {
    if ($n == 1) {
        $point = array(
            "ts"    => $row['datetime'],
            "t1bot" => floatval($row['T1BOT'])/100,
            "t2bot" => floatval($row['T2BOT'])/100,
            "t3bot" => floatval($row['T3BOT'])/100,
            "t1mid" => floatval($row['T1MID'])/100,
            "t2mid" => floatval($row['T2MID'])/100,
            "t3mid" => floatval($row['T3MID'])/100,
            "t1top" => floatval($row['T1TOP'])/100,
            "t2top" => floatval($row['T2TOP'])/100,
            "t3top" => floatval($row['T3TOP'])/100,
            "tout"  => floatval($row['TOUT'])/100
        );

        array_push($data_points, $point);
        $n = 0;
    } else {
        $n++;
    }
}

// Check if data points array is empty
if (empty($data_points)) {
    die("No data points generated.");
}

// Output the results in JSON format
header('Content-Type: application/json');
echo json_encode($data_points, JSON_NUMERIC_CHECK);

// Free up the result resources
$result->free();

// Close the database connection
$connect->close();

?>
