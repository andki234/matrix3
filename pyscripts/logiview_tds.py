import socket   
import json
import mysql.connector
import setproctitle
import logging
import sys  

# Flag to indicate if Ctrl-C was pressed
ctrl_c_pressed = False

def calculate_internal_energy_kwh(mass_grams, specific_heat, temperature):
    energy_joules = mass_grams * specific_heat * temperature
    energy_kwh = energy_joules / (3.6 * 10**6)
    return energy_kwh

def energy_to_percentage(energy_kwh, energy_min, energy_max):
    percentage = (energy_kwh - energy_min) / (energy_max - energy_min) * 100
    return round(percentage)
    
def connect_to_database():
    try:
        cnx = mysql.connector.connect(
            user='pi',
            password='8Fx5AewqQ9TmsF9oeuN4Ib0s84gXt0',
            host='192.168.0.240',
            database='logiview'
        )
        return cnx
    except mysql.connector.Error as err:
        if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
            logger.error("MySQL connection error: Incorrect username or password")
        else:
            logger.error("MySQL connection error: %s", err)
    return None
    

 
def main():
    setproctitle.setproctitle('biolertemps')
    
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('boilertemps')
    
    # Configure the logging module
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Variable to control whether info logging is enabled or disabled
    enable_info_logging = True
    
    # Connect to database
    cnx = connect_to_database()
    
    if cnx:
        cursor = cnx.cursor(buffered=False)

        sqlquery = "SELECT * FROM logiview.tempdata order by datetime desc limit 1"

        # next create a socket object
        s = socket.socket()
        logging.info("Socket successfully created")

        port = 45120

        s.bind(('', port))
        logging.info("socket binded to %s" % (port))

        s.listen(5)
        logging.info("socket is listening")

        try:
            while True:
                c, addr = s.accept()
                logging.info('Got connection from %s', addr)

                cursor.execute(sqlquery)

                fields = [field_md[0] for field_md in cursor.description]
                result = [dict(zip(fields, row)) for row in cursor.fetchall()]

                sensors = ["T1TOP", "T1MID", "T1BOT", "T2TOP", "T2MID", "T2BOT", "T3TOP", "T3MID", "T3BOT"]
                temps = [0.00] * len(sensors)
                percentage_str = [""] * 3

                for sensor in sensors:
                    try:
                        temps[sensors.index(sensor)] = bytes((str(float(result[0][sensor]) / 100.0) + '\n'), 'utf-8')
                    except:
                        temps[sensors.index(sensor)] = b'''0.00'''

                # Calculate energy in the tanks and send result in %. 0% is mtemp < 35degC and 100% is mtemp > 75degC	
            
                specific_heat = 4.186  # Specific heat capacity of water in J/g°C
                
                
                # Temperature of the water in °C tank 1
                #--------------------------------------
                internal_energy_kwh  = calculate_internal_energy_kwh(200000, specific_heat, (float(temps[sensors.index("T1TOP")])))
                internal_energy_kwh += calculate_internal_energy_kwh(200000, specific_heat, (float(temps[sensors.index("T1MID")])))
                internal_energy_kwh += calculate_internal_energy_kwh(50000 , specific_heat, (float(temps[sensors.index("T1BOT")])))
                
            
                energy_min = 20  # Minimum energy value
                energy_max = 42  # Maximum energy value
                percentage_str[0] = str(energy_to_percentage(internal_energy_kwh, energy_min, energy_max))
                print(f"{internal_energy_kwh} kWh is approximately {float(percentage_str[0]):.2f}%")
                
                # Temperature of the water in °C tank 2
                #--------------------------------------
                mass_grams = 750000  # 750 liters of water in grams
                temperature = (float(temps[sensors.index("T2TOP")]) + float(temps[sensors.index("T2MID")]) + float(temps[sensors.index("T2BOT")])) / 3.0
                print(temperature)
                
                internal_energy_kwh = calculate_internal_energy_kwh(mass_grams, specific_heat, temperature)
                print(f"Total energy contained at {temperature}°C: {internal_energy_kwh:.2f} kWh")
                
                energy_min = 30  # Minimum energy value
                energy_max = 74  # Maximum energy value
                percentage_str[1] = str(energy_to_percentage(internal_energy_kwh, energy_min, energy_max))
                print(f"{internal_energy_kwh} kWh is approximately {float(percentage_str[1]):.2f}%")
                
                # Temperature of the water in °C tank 3
                #--------------------------------------
                mass_grams = 750000  # 750 liters of water in grams
                temperature = (float(temps[sensors.index("T3TOP")]) + float(temps[sensors.index("T3MID")]) + float(temps[sensors.index("T3BOT")])) / 3.0
                print(temperature)
            
                internal_energy_kwh = calculate_internal_energy_kwh(mass_grams, specific_heat, temperature)
                #print(f"Total energy contained at {temperature}°C: {internal_energy_kwh:.2f} kWh")

                energy_min = 30  # Minimum energy value
                energy_max = 74  # Maximum energy value
                percentage_str[2] = str(energy_to_percentage(internal_energy_kwh, energy_min, energy_max))
                print(f"{internal_energy_kwh} kWh is approximately {float(percentage_str[2]):.2f}%")		

                jstr = json.dumps({"T1P": percentage_str[0], "T2P": percentage_str[1], "T3P": percentage_str[2]})
                c.send(jstr.encode())
                if enable_info_logging:
                    logging.info(jstr)

                c.close()
                cnx.rollback()

            c.close()
            s.close()
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, exiting.")
        except OSError as e:
            logger.error("Socket error: %s", e)
        except Exception as e:
            logger.error("An error occurred: %s", e)
        finally:
            s.close()
            cnx.close()
    else:
        logging.error("Database connection is not available.")
   

if __name__ == "__main__":
    main()
