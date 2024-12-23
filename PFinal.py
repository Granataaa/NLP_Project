from DBLibrary import selectQuery, commitQuery
from dotenv import load_dotenv
import os
from openai import OpenAI
import requests
from datetime import date

load_dotenv()
key = os.getenv("OPENAI_API_KEY")

client = OpenAI(
  organization=os.getenv("ORGANIZATION"),
  project=os.getenv("PROJECT"),
)

url = "https://api.openai.com/v1/chat/completions"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {key}"
}

memoria = []

#funzione per le richieste a gpt
def AIRequest(mess):

    global memoria
    memoria.append({"role": "user", "content": mess})
    payload = {
        "model": "gpt-4o",
        "messages": memoria,
        "max_tokens": 1000,
        "temperature": 1.0
    }
    response = requests.post(url, json=payload, headers=headers)
    r = ""
    memoria.pop()
    if response.status_code == 200:
        result = response.json()
        r = result['choices'][0]['message']['content']
    else:
        print(f"Errore: {response.status_code}, Dettagli: {response.text}")
    return r

#fin quando l'utente scrive exit
while(True):
    #memoria capienza massima 20 richieste, per la 21esima elimina la prima
    if len(memoria) >= 20*2:
        memoria.pop(0)
        memoria.pop(0)

    oggi = date.today()

    #prende le tabelle e le loro descrizioni
    q = f"""SELECT table_name, table_comment
    FROM information_schema.tables
    WHERE table_schema = 'nlp_project'"""
    res = selectQuery(q,1)

    #prende e mette in una lista tutti i nomi delle tabelle
    qtables = f"""SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'nlp_project'"""
    tables = selectQuery(qtables,1)[0]
    tables = [t[0] for t in tables]
    
    #prende l'input dall'utente e lo aggiunge alla memoria
    inp = input("\n>> ")
    if inp == "exit":
        break
    else:
        memoria.append({"role": "user", "content": inp})

    #capisce di che tabella stiamo parlando
    mess_send = f"""Considerando questo input dell'utente "{inp}"
    e considerando le seguenti tabelle nel formato (nome_tabella, descrizione_tabella): {res}
    Dimmi i nome_tabella a cui si riferisce l'input considerando le descrizioni. Rispondimi solo con i nomi delle tabelle.
    """
    tab = AIRequest(mess_send)

    #trasformazione della stringa in lista e query describe
    tabs = ""
    TableDescription = []
    tabList = []
    if "," in tab:
        split = tab.split(",")
        counter_virgola = 0
        for s in split:
            tabs += f"'{s.replace(' ','')}'"
            if counter_virgola < len(split)-1:
                tabs += f", "
            counter_virgola+=1
            queryDescr = f"DESCRIBE {s}"
            TableDescription.append(selectQuery(queryDescr))
            tabList.append(f"{s.replace(' ','')}")
    else:
        tabs += f"'{tab.replace(' ','')}'"
        queryDescr = f"DESCRIBE {tab}"
        TableDescription.append(selectQuery(queryDescr)) 
        tabList.append(f"{tab.replace(' ','')}")


    #se non presente nelle tabelle va al prossimo ciclo
    flag = False
    for t in tabList:
        if t not in tables:
            print("non ci occupiamo di questo campo, prova con qualcos'altro\n")
            flag = True
            break
    if flag == True:
        continue

    #prende i campi e le descrizioni della tabella che ha selezionato
    q2 = f"""SELECT table_name, column_name, column_comment
    FROM information_schema.columns
    WHERE table_schema = 'nlp_project' 
    AND table_name IN ({tabs})
    ORDER BY table_name"""
    info_campi_db = selectQuery(q2,1)

    #capisce se vogliamo fare un inserimento o qualsiasi altra operazione sul db
    mess_send = f"""considerando l'input dell'utente: "{inp}",
    dimmi se ha intenzione di fare un inserimento di dati,
    rispondimi con la parola: "inserimento" oppure "ricerca" se vuole fare una ricerca, un aggiornamento o un cancellamento
    """
    azione = AIRequest(mess_send)

    if azione != "inserimento":
        
        #crazione query select, delete o update
        mess_send = f"""Considerando che questo è l'input dell'utente: \"{inp}\" se serve considera che oggi è il {oggi}"
        e tieni in considerazione che questa è/sono la/e tabella/e del DB che serve/servono con 
        (il primo elemento è il nome della tabella, il secondo il nome dell attributo e il terzo la descrizione) \"{info_campi_db}\" e \"{tab}\" il nome della tabella
        crea una query che soddisfi i dati inseriti dall'utente
        e utilizzarli come filtri della query. Se necessario genera più query e rispondimi solo con il testo della/e query creata/e"""

        query = AIRequest(mess_send)
        print(f"\nquery : {query}\n")
        if "sql" in query:
            query = query.split("```")[1].replace("sql","")

        #fa la query
        query_response = selectQuery(query, 1)
        if not query_response:
            print("\nnessun risultato nel db\n")
            continue

        #riformulazione risultato
        mess_send = f"""questo è il risultato di una query: "{query_response}"
        riformula quello che c'è scritto anche in base all'input dell'utente: "{inp}"
        e anche considerando che la risposta della query è composta da questi campi: "{info_campi_db}"
        ognuno di questi campi è messo nel seguente formato: [nome_tabella, nome_campo, descrizione_campo], tralascia l'id.
        puoi parlare anche in maniera informale senza specificare quello che hai fatto
        """
        res_riformulato = AIRequest(mess_send)
        memoria.append({"role": "assistant", "content": res_riformulato})
        print(f"\nassistant : {res_riformulato}\n")

    else: #inserimento

        #query per prendere anche le tabelle che sono in relazione con quelle citate
        q = f"""
            SELECT 
                TABLE_NAME AS TableName,
                COLUMN_NAME AS ColumnName,
                CONSTRAINT_NAME AS ConstraintName,
                REFERENCED_TABLE_NAME AS ReferencedTableName,
                REFERENCED_COLUMN_NAME AS ReferencedColumnName
            FROM 
                INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE 
                TABLE_NAME IN ({tabs})
                AND REFERENCED_TABLE_NAME IS NOT NULL;
        """
        relazioniTab = selectQuery(q)[0]

        #adattiamo l'inserimento con la relazione
        relMess = ""
        if relazioniTab: #se ci sono relazioni
            relTabs = ''
            tot = 0
            for rTabs in relazioniTab:
                relTabs += f"'{rTabs[3]}'"
                if tot< len(relazioniTab)-1:
                    tot += 1
                    relTabs += ", "

            #query per prendere le colonne e i commenti delle tabelle in relazione
            q2 = f"""SELECT table_name, column_name, column_comment
            FROM information_schema.columns
            WHERE table_schema = 'nlp_project' 
            AND table_name IN ({relTabs})
            ORDER BY table_name"""
            info_campi_db_relazioni = selectQuery(q2,1)

            #prende le chiavi esterne e gli attributi delle tabelle in relazione
            mess_send = f"""dipendentemente dall'input dell'utente: {inp}, dalla descrizioni delle/a tabelle/a {info_campi_db} nel formato [nome_tabella, nome_campo, descrizione_campo],
            dalle loro relazioni: {relazioniTab} in questo formato: [table_name, column_name, constraint_name, referenced_table_name, referenced_column_name]
            e dalle descrizioni delle tabelle in relazione: {info_campi_db_relazioni}, allora
            creami una query che prende tutte (se ce n'è più di una) le referenced_column_name e tutti gli altri campi di quel record dalle tabelle referenced_table_name in base all'input dell'utente.
            stampa solo la query
            """
            dato = AIRequest(mess_send)
            print(dato + "\n")
            query = dato.split("```")[1].replace("sql","")
            id = selectQuery(query)

            #creazione messaggio da inserire nella richiesta finale con le informazioni sulle relazioni
            relMess = f"""in base alle relazioni: {relazioniTab} in questo formato: [table_name, column_name, constraint_name, referenced_table_name, referenced_column_name]
            collega le column_name di table_name alle corrette referenced_column_name di referenced_table_name considerando che queste sono le chiavi e gli attributi corretti: {id}
            considerando queste descrizioni delle tabelle relazionate: {info_campi_db_relazioni}
            """

        #se non ci sono relazioni fa direttamente questo
        #messaggio per richiesta finale in cui creiamo la query insert solo se tutti i dati sono presenti
        mess_send = f"""dipendentemente da {TableDescription} che è un describe fatto sulla/e tabella/e del database
        vedi scrupolosamente se all'interno dell'input dell'utente: "{inp}" sono presenti tutti i dati necessari per fare un inserimento nel database,
        i dati che non sono necessari sono quelli in cui all'interno del describe, nel terzo campo, c'è scritto "SI".
        {relMess}
        Se ci sono tutti i dati allora crea e stampa SOLO una (o se serve più) query di inserimento sempre stando attento ai tipi dei dati 
        (scritti nel describe, tipo quando c'è una data e non un orario inserire orario di default e altre cose del genere e non inserire gli id perchè il db usa l'auto_increment!!)
        e alle descrizioni dei dati (scritti in {info_campi_db} nel formato [nome_tabella, nome_campo, descrizione_campo]),
        se serve cambiare l'input dell'utente per adattarlo ai dati fallo tranquillamente.
        se mancano dati rispondi con "mancano dati" + e dimmi quali mancano sennò SOLAMENTE con la/e query
        """
        presenza_dati = AIRequest(mess_send)
        print(presenza_dati + "\n")
        memoria.append({"role": "assistant", "content": presenza_dati})

        if "mancano dati" in presenza_dati:
            print("mancano dati obbligatori, impossibile fare l'inserimento\n")
            continue
        
        query = presenza_dati.split("```")[1].replace("sql","")

        selectQuery(query)