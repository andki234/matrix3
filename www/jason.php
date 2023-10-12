<!DOCTYPE HTML>
<html>
<head>  
<script src="http://code.jquery.com/jquery-3.5.1.min.js"></script>
<script>

  
window.onload = function () {

    console.log( "complete" );

    $.getJSON("tempdb.php", function(result){
	var t1bot= [];
	var t2bot= [];
	var t3bot= [];
	var t1mid= [];
        var t2mid= [];
        var t3mid= [];
	var t1top= [];
        var t2top= [];
        var t3top= [];
	var tout= [];
	
	//Insert Array Assignment function here
	for(var i=0; i<result.length;i++) {
	    t1bot.push({"label":result[i].ts, "y":result[i].t1bot});
	    t2bot.push({"label":result[i].ts, "y":result[i].t2bot});
            t3bot.push({"label":result[i].ts, "y":result[i].t3bot});
	    t1mid.push({"label":result[i].ts, "y":result[i].t1mid});
            t2mid.push({"label":result[i].ts, "y":result[i].t2mid});
            t3mid.push({"label":result[i].ts, "y":result[i].t3mid});
	    t1top.push({"label":result[i].ts, "y":result[i].t1top});
            t2top.push({"label":result[i].ts, "y":result[i].t2top});
            t3top.push({"label":result[i].ts, "y":result[i].t3top});

	    mtemp = (result[i].t1bot / 16) + (result[i].t2bot + result[i].t3bot +
		result[i].t1mid + result[i].t2mid + result[i].t3mid +
		result[i].t1top + result[i].t2top + result[i].t3top) / 8 
	    
	    tout.push({"label":result[i].ts, "y":mtemp});
	}

	//Insert Chart-making function here
	var chart = new CanvasJS.Chart("chartContainer", {
	    zoomEnabled:true,
	    panEnabled:true,
	    height:1000,
	    animationEnabled:true,

	    title:{
		text: "Tank temperatures"
	    },

	    legend: {
		fontSize: 14
	    },

	    toolTip:{
		shared: true
	    },
	    
	    axisX:{
		title: "TimeStamp",
		labelFontSize: 14
	    },

            axisY:[
	    {
		title: "TANK 1",
		labelFontSize: 14,
		maximum: 100,
		minimum: -20
	    }],
	    
	    data: [
	    {
		type: "spline",
		name: "T1TOP",
		showInLegend: true,
		dataPoints:
		t1top
            },
	    {
		type: "spline",
		name: "T1MID",
		axisYIndex: 1,
		showInLegend: true,
                dataPoints:
                t1mid

	    },
            {
                type: "spline",
		name: "T1BOT",
                axisYIndex: 2,
		lineColor: "black",
		showInLegend: true,
                dataPoints:
                t1bot
            },
	    {
                type: "spline",
                name: "T2TOP",
		axisYIndex: 3,
                showInLegend: true,
                dataPoints:
                t2top
            },
            {
                type: "spline",
                name: "T2MID",
                axisYIndex: 4,
                showInLegend: true,
                dataPoints:
                t2mid

            },
            {
                type: "spline",
                name: "T2BOT",
                axisYIndex: 5,
                showInLegend: true,
                dataPoints:
                t2bot
            },
	    {
                type: "spline",
                name: "T3TOP",
		axisYIndex: 6,
                showInLegend: true,
                dataPoints:
                t3top
            },
            {
                type: "spline",
                name: "T3MID",
                axisYIndex: 7,
	        showInLegend: true,
                dataPoints:
                t3mid

            },
            {
                type: "spline",
                name: "T3BOT",
                axisYIndex: 8,
                showInLegend: true,
                dataPoints:
                t3bot
            },
	    {
                type: "spline",
                name: "MTEP",
                axisYIndex: 9,
		lineThickness: 6,
		lineColor: "red",
                showInLegend: true,
                dataPoints:
                tout
            },
	    ]
	});
	chart.render();
	
    })
	//.done(function() { alert("second success"); })
	.fail(function() { alert("error"); });
	//.always(function() { alert("complete"); 
}
</script>
</head>
<body>
<div id="chartContainer" style="height: 370px; width: 100%;"></div>
<script src="https://canvasjs.com/assets/script/canvasjs.min.js"></script>
</body>
</html>
