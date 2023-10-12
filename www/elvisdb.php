<?php

error_reporting(E_ALL);
ini_set('display_errors', 1);

$servername = "192.168.0.240";
$username = "pi";
$password = "b%HcSLYsFqOp7E0B*ER8#!";
$dbname = "elvis";

/* Create database  connection with correct username and password*/
$connect = new mysqli("$servername","$username","$password","$dbname");

/* Check the connection is created properly or not */
if($connect->connect_error)
    echo "Connection error:" .$connect->connect_error;
else
    #echo "Connection is created successfully <br>";

    // Perform query
    if ($result = $connect->query("SELECT * FROM smartmeter where datetime >=  NOW() - INTERVAL 5 DAY order by datetime LIMIT 100000")) {
        #echo "Returned rows are: " . $result -> num_rows . "<br>";
	$data_points = array();
        if (mysqli_num_rows($result) > 0) {
	#echo '<pre>'; print_r($result); echo '</pre>';
	$n = 0;
	while($row = mysqli_fetch_assoc($result)) {
                /* Push the results in our array */	
              	$point = array("ts" =>  $row['datetime'] ,
		"I1" => floatval($row['I1']), "I2" =>  floatval($row['I2']), "I3" => floatval($row['I3']),
		"V1" => floatval($row['V1']), "V2" =>  floatval($row['V2']), "V3" => floatval($row['V3']),
		"TotkWh" => floatval($row['TotKWh']), "PkW" =>  floatval($row['PkW']));
		#echo 'point = <pre>'; print_r($point); echo '</pre>';
                array_push($data_points, $point);
		#echo 'data_points = <pre>'; print_r($data_points); echo '</pre>';
            }

	/* Encode this array in JSON form */
        echo json_encode($data_points, JSON_NUMERIC_CHECK);
    }

       // Free result set
       mysqli_close($connect);

}

?>
     
