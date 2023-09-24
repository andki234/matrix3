import ctypes
import logging
import unittest
import setproctitle
import sys
import time
import snap7
import mysql.connector

logging.basicConfig(level=logging.WARNING)

# Set to appropriate value to for logging level
LOGING_LEVEL = logging.WARNING

tcpport = 102


def mainloop():
    setproctitle.setproctitle("logo8_server")

    # Setup the logging
    logging.basicConfig(
        level=LOGING_LEVEL, format="%(filename)s:%(lineno)d - %(message)s"
    )

    server = snap7.server.Server()

    size = 128
    dataDB1 = (snap7.types.wordlen_to_ctypes[snap7.types.S7WLByte] * size)()
    dataPE1 = (snap7.types.wordlen_to_ctypes[snap7.types.S7WLByte] * size)()

    server.register_area(snap7.types.srvAreaDB, 1, dataDB1)
    server.register_area(snap7.types.srvAreaPE, 1, dataPE1)

    server.start(tcpport=tcpport)

    try:
        cnx = mysql.connector.connect(
            user="pi",
            password="b%HcSLYsFqOp7E0B*ER8#!",
            host="192.168.0.240",
            database="logiview",
        )
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            print("Something is wrong with your user name or password")
        else:
            print(err)

    cursor = cnx.cursor(buffered=False)

    # Be shure that you get correct data eaven if database changes!

    sqlstr = "SELECT %s FROM logiview.tempdata order by datetime desc limit 1"

    sqlqT1TOP = sqlstr % "T1TOP"
    sqlqT2TOP = sqlstr % "T2TOP"
    sqlqT3TOP = sqlstr % "T3TOP"
    sqlqT1MID = sqlstr % "T1MID"
    sqlqT2MID = sqlstr % "T2MID"
    sqlqT3MID = sqlstr % "T3MID"
    sqlqT1BOT = sqlstr % "T1BOT"
    sqlqT2BOT = sqlstr % "T2BOT"
    sqlqT3BOT = sqlstr % "T3BOT"

    while True:
        # FIXA EN SUB!

        # T1TOP
        cursor.execute(sqlqT1TOP)
        sqldata = cursor.fetchall()
        cnx.rollback()

        x = int(sqldata[0][0])
        print(x)
        dataDB1[0] = (x & 0xFF00) >> 8
        dataDB1[1] = int(x & 0x00FF)

        # T1MID
        cursor.execute(sqlqT1MID)
        sqldata = cursor.fetchall()
        cnx.rollback()

        x = int(sqldata[0][0])
        print(x)
        dataDB1[2] = (x & 0xFF00) >> 8
        dataDB1[3] = int(x & 0x00FF)

        # T1BOT
        cursor.execute(sqlqT1BOT)
        sqldata = cursor.fetchall()
        cnx.rollback()

        x = int(sqldata[0][0])
        print(x)
        dataDB1[4] = (x & 0xFF00) >> 8
        dataDB1[5] = int(x & 0x00FF)

        # T2TOP
        cursor.execute(sqlqT2TOP)
        sqldata = cursor.fetchall()
        cnx.rollback()

        x = int(sqldata[0][0])
        print(x)
        dataDB1[6] = (x & 0xFF00) >> 8
        dataDB1[7] = int(x & 0x00FF)

        # T2MID
        cursor.execute(sqlqT2MID)
        sqldata = cursor.fetchall()
        cnx.rollback()

        x = int(sqldata[0][0])
        print(x)
        dataDB1[8] = (x & 0xFF00) >> 8
        dataDB1[9] = int(x & 0x00FF)

        # T2BOT
        cursor.execute(sqlqT2BOT)
        sqldata = cursor.fetchall()
        cnx.rollback()

        x = int(sqldata[0][0])
        print(x)
        dataDB1[10] = (x & 0xFF00) >> 8
        dataDB1[11] = int(x & 0x00FF)

        # T3TOP
        cursor.execute(sqlqT3TOP)
        sqldata = cursor.fetchall()
        cnx.rollback()

        x = int(sqldata[0][0])
        print(x)
        dataDB1[12] = (x & 0xFF00) >> 8
        dataDB1[13] = int(x & 0x00FF)

        # T3MID
        cursor.execute(sqlqT3MID)
        sqldata = cursor.fetchall()
        cnx.rollback()

        x = int(sqldata[0][0])
        print(x)
        dataDB1[14] = (x & 0xFF00) >> 8
        dataDB1[15] = int(x & 0x00FF)

        # T3BOT
        cursor.execute(sqlqT3BOT)
        sqldata = cursor.fetchall()
        cnx.rollback()

        x = int(sqldata[0][0])
        print(x)
        dataDB1[16] = (x & 0xFF00) >> 8
        dataDB1[17] = int(x & 0x00FF)

        while True:
            event = server.pick_event()
            if event:
                # print(str(round(float(sqldata[sqldata.index("T1TOP") - 1]), 1)))
                logging.info(server.event_text(event))
                dataPE1[0] = 1
            else:
                break
        time.sleep(5)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        snap7.common.load_library(sys.argv[1])
    mainloop()
