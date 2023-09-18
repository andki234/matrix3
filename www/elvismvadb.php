<?php

// Database connection details
$servername = "192.168.0.240";
$username = "pi";
$password = "b%HcSLYsFqOp7E0B*ER8#!";
$dbname = "elvis";
$dbtable = "smartmeter";

// Get the start date as a parameter (format: 'YYYY-MM-DD')
$start_date = $_GET['start_date']; 

// Calculate the end date as the day before the current day
$end_date = date('Y-m-d', strtotime('-1 day')); 

// Create connection
$conn = new mysqli($servername, $username, $password, $dbname);

// Check connection
if ($conn->connect_error) {
   die("Connection failed: " . $conn->connect_error);
}
else {
   //echo "Connected successfully<br>";
}

// Return TotKWh data for every day last entry of the day - first entry of the day. Fields are datetime and TotKWh
$sql = "SELECT DATE(datetime) AS date, MAX(TotKWh) - MIN(TotKWh) AS DifferenceKWh FROM $dbtable WHERE datetime BETWEEN '$start_date' AND '$end_date' GROUP BY DATE(datetime) ORDER BY DATE(datetime) ASC";

// Execute the query
$result = $conn->query($sql);

// Check if there are any rows returned by the query and return them in JSON format
if ($result->num_rows > 0) {
   // Output data of each row
   $rows = array();
   while($row = $result->fetch_assoc()) {
      $rows[] = $row;
   }

   // Calculate the 14-day moving average for each day
   $movingAverages = array();
   $windowSize = 14;
   $rowCount = count($rows);

   for ($i = 0; $i < $rowCount; $i++) {
      if ($i < $windowSize - 1) {
         // If there are not enough data points for a 7-day window, set moving average to 0
         $movingAverages[] = array_merge($rows[$i], ['MovingAverages' => 0]);
      } else {
         $sum = 0;
         for ($j = $i - $windowSize + 1; $j <= $i; $j++) {
            $sum += $rows[$j]['DifferenceKWh'];
         }
         $movingAverage = $sum / $windowSize;
         $movingAverages[] = array_merge($rows[$i], ['MovingAverages' => $movingAverage]);
      }
   }

   echo json_encode($movingAverages);

   // Close connection
   $conn->close();
} else {
   echo "0 results";
}
?>
