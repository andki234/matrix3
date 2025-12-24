<?php
// Increase memory and execution time limits for large datasets
ini_set('memory_limit', '512M');
ini_set('max_execution_time', 300);

// Turn off error display but log errors
error_reporting(E_ALL);
ini_set('display_errors', 0);  // Don't display errors as HTML
ini_set('log_errors', 1);       // Log errors instead

// Ensure clean JSON output
ob_start();

try {
    $config = require 'logiview_db_config.php';

    $connect = new mysqli($config['servername'], $config['username'], $config['password'], $config['dbname']);

    if ($connect->connect_error) {
        throw new Exception("Connection error: " . $connect->connect_error);
    }

    $startDate = isset($_GET['startDate']) ? $_GET['startDate'] : date('Y-m-d', strtotime('-7 days'));
    $endDate = isset($_GET['endDate']) ? $_GET['endDate'] : date('Y-m-d');

    $dateTimePattern = '/^\d{4}-\d{2}-\d{2}(?:\s\d{2}:\d{2}:\d{2})?$/';
    if (!preg_match($dateTimePattern, $startDate) || !preg_match($dateTimePattern, $endDate)) {
        throw new Exception("Invalid date-time format. Expected format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS.");
    }

    if (strlen($startDate) == 10) {
        $startDate .= " 00:00:00";
    }
    if (strlen($endDate) == 10) {
        $endDate .= " 23:59:59";
    }

    // Calculate the date range in days to determine sampling rate
    $start = new DateTime($startDate);
    $end = new DateTime($endDate);
    $daysDiff = $end->diff($start)->days;

    // Determine sampling rate based on date range
    $samplingRate = 1; // Default: take every record
    if ($daysDiff > 180) {
        $samplingRate = 50; // For more than 6 months, take every 50th record
    } elseif ($daysDiff > 90) {
        $samplingRate = 30; // For more than 90 days, take every 30th record
    } elseif ($daysDiff > 60) {
        $samplingRate = 20; // For more than 60 days, take every 20th record
    } elseif ($daysDiff > 30) {
        $samplingRate = 10; // For more than 30 days, take every 10th record
    } elseif ($daysDiff > 14) {
        $samplingRate = 5;  // For more than 14 days, take every 5th record
    } elseif ($daysDiff > 7) {
        $samplingRate = 2;  // For more than 7 days, take every 2nd record
    }

    // Reduce safety limit for very large date ranges
    $maxPoints = 20000;
    if ($daysDiff > 90) {
        $maxPoints = 5000;  // Further reduced for very large ranges
    } elseif ($daysDiff > 30) {
        $maxPoints = 10000;
    }

    $stmt = $connect->prepare("SELECT * FROM tempdata WHERE datetime BETWEEN ? AND ? ORDER BY datetime");
    if (!$stmt) {
        throw new Exception("Prepare failed: " . $connect->error);
    }
    
    $stmt->bind_param('ss', $startDate, $endDate);

    // Debug: Log the date range being queried
    error_log("Querying database for date range: $startDate to $endDate");
    error_log("Day difference: $daysDiff, Sampling rate: $samplingRate, Max points: $maxPoints");

    if (!$stmt->execute()) {
        throw new Exception("Execute failed: " . $stmt->error);
    }

    $result = $stmt->get_result();
    if (!$result) {
        throw new Exception("Get result failed: " . $connect->error);
    }
    
    $data_points = array();
    $n = 0;
    $first_record = null;
    $last_record = null;

    while ($row = $result->fetch_assoc()) {
        if ($n % $samplingRate == 0) {
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
                "tbtop" => floatval($row['TBTOP']) / 100,
                "tout" => floatval($row['TOUT']) / 100,
                "tret" => floatval($row['TRET']) / 100,
                "bp" => floatval($row['BP']) * 30,
                "pt1t2" => floatval($row['PT1T2']) * 20,
                "pt2t1" => floatval($row['PT2T1']) * 10,
            );
            array_push($data_points, $point);
            
            // Track first and last records
            if ($first_record === null) {
                $first_record = $row['datetime'];
            }
            $last_record = $row['datetime'];
            
            // Safety limit to prevent memory issues
            if (count($data_points) >= $maxPoints) {
                error_log("Reached safety limit of $maxPoints points, stopping data collection");
                break;
            }
        }
        $n++;
    }

    // Debug: Log the actual date range returned
    error_log("First record: $first_record, Last record: $last_record, Total points: " . count($data_points));

    if (empty($data_points)) {
        throw new Exception("No data points found for the specified date range.");
    }

    // Clean any output buffer content
    ob_clean();
    
    header('Content-Type: application/json');
    echo json_encode($data_points, JSON_NUMERIC_CHECK);

    $result->free();
    $connect->close();

} catch (Exception $e) {
    // Clean any output buffer content
    ob_clean();
    
    error_log("Database error: " . $e->getMessage());
    header('Content-Type: application/json');
    echo json_encode(["error" => $e->getMessage()]);
    exit;
}

// End output buffering
ob_end_flush();
?>
