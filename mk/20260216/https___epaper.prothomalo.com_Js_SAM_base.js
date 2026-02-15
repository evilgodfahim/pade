window.SAMConfig = [];

function processInsertDataRequest(activityArgs) {

    try {
        var baseUrl = sam_APIBaseURL;
        var APIKey = sessionStorage.getItem('APIKey')
        if (APIKey == undefined || APIKey == 0 || APIKey == "null" || APIKey == false || APIKey == '') {

            //console.log("SAM API Key missing. No call being made to API");
        }
        else {
            if (baseUrl == "") {
                console.log("Base URL missing for SAM API. Please check configuration");
            }
            else {
                if (activityArgs.eventname != null) {
                    var capturedTime = getDateTime();
                    activityArgs.timestamp = capturedTime.dateTime;
                    activityArgs.month = capturedTime.month;
                    activityArgs.day = capturedTime.datenumber;
                    //Get current edition date selected
                    var currenteditiondate = $.cookie("changeddate");
                    if (currenteditiondate == undefined || currenteditiondate == 0 || currenteditiondate == "null" || currenteditiondate == false || currenteditiondate == '') {
                        activityArgs.content_days_old = 0;
                    }
                    else {
                        var convertcurrentdate = stringToDate(currenteditiondate, "dd/MM/yyyy", "/");
                        var currentDate = new Date(capturedTime.date);
                        const diffTime = Math.abs(currentDate - convertcurrentdate);
                        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
                        activityArgs.content_days_old = diffDays;
                    }

                    //Get current time spend data
                    if (activityArgs.eventname == "Logout") {
                        var sessionStartDateTime = sessionStorage.getItem("sessionStartTime");
                        if (sessionStartDateTime == undefined || sessionStartDateTime == 0 || sessionStartDateTime == "null" || sessionStartDateTime == false || sessionStartDateTime == '') {
                            activityArgs.Timespend = 0;
                        }
                        else {
                            var sessionEndDateTime = new Date();
                            var sessionStartDateTimeConverted = new Date(sessionStartDateTime);
                            var totalTimeSpendInSeconds = (sessionEndDateTime.getTime() - sessionStartDateTimeConverted.getTime()) / 1000;
                            activityArgs.Timespend = totalTimeSpendInSeconds;
                        }
                    }

                    //Get time of day data
                    if (capturedTime.hour == "00") {
                        activityArgs.time_of_day = "Night"
                    }
                    if (capturedTime.hour == "01") {
                        activityArgs.time_of_day = "Night"
                    }
                    if (capturedTime.hour == "02") {
                        activityArgs.time_of_day = "Night"
                    }
                    if (capturedTime.hour == "03") {
                        activityArgs.time_of_day = "Night"
                    }
                    if (capturedTime.hour == "04") {
                        activityArgs.time_of_day = "Night"
                    }
                    if (capturedTime.hour == "05") {
                        activityArgs.time_of_day = "Night"
                    }
                    if (capturedTime.hour == "06") {
                        activityArgs.time_of_day = "Morning"
                    }
                    if (capturedTime.hour == "07") {
                        activityArgs.time_of_day = "Morning"
                    }
                    if (capturedTime.hour == "08") {
                        activityArgs.time_of_day = "Morning"
                    }
                    if (capturedTime.hour == "09") {
                        activityArgs.time_of_day = "Morning"
                    }
                    if (capturedTime.hour == "10") {
                        activityArgs.time_of_day = "Morning"
                    }
                    if (capturedTime.hour == "11") {
                        activityArgs.time_of_day = "Morning"
                    }
                    if (capturedTime.hour == "12") {
                        activityArgs.time_of_day = "Afternoon"
                    }
                    if (capturedTime.hour == "13") {
                        activityArgs.time_of_day = "Afternoon"
                    }
                    if (capturedTime.hour == "14") {
                        activityArgs.time_of_day = "Afternoon"
                    }
                    if (capturedTime.hour == "15") {
                        activityArgs.time_of_day = "Afternoon"
                    }
                    if (capturedTime.hour == "16") {
                        activityArgs.time_of_day = "Afternoon"
                    }
                    if (capturedTime.hour == "17") {
                        activityArgs.time_of_day = "Evening"
                    }
                    if (capturedTime.hour == "18") {
                        activityArgs.time_of_day = "Evening"
                    }
                    if (capturedTime.hour == "19") {
                        activityArgs.time_of_day = "Evening"
                    }
                    if (capturedTime.hour == "20") {
                        activityArgs.time_of_day = "Night"
                    }
                    if (capturedTime.hour == "21") {
                        activityArgs.time_of_day = "Night"
                    }
                    if (capturedTime.hour == "22") {
                        activityArgs.time_of_day = "Night"
                    }
                    if (capturedTime.hour == "23") {
                        activityArgs.time_of_day = "Night"
                    }
                    if (capturedTime.hour == "24") {
                        activityArgs.time_of_day = "Night"
                    }
                    
                    activityArgs.FQ = quarter_of_the_year();
                    activityArgs.FY = getCurrentFinancialYear();
                    activityArgs.week_of_Month = getWeekOfMonth();
                    activityArgs.ip = sessionStorage.getItem('currentip');
                    activityArgs.APIKey = APIKey;

                    //Try to capture here as much info as possible for data correctness
                    //Current URL
                    if (activityArgs.eventname == "Share Article" || activityArgs.eventname == "Image view" || activityArgs.eventname == "Article view") {
                        activityArgs.webpage = window.location.protocol + "/" + window.location.host + "/" + activityArgs.webpage;
                    }
                    else {
                        activityArgs.webpage = window.location.href;
                    }
                    
                    //Current publication (taken from config)
                    var PublicationNameConfig = sessionStorage.getItem("PublicationNameConfig");
                    if (PublicationNameConfig) {
                        activityArgs.Publication = PublicationNameConfig;
                    }

                    //All session storage items 
                    activityArgs.Login_mode = sessionStorage.getItem("Login_mode");
                    activityArgs.reg_mode = sessionStorage.getItem("reg_mode");
                    activityArgs.user_type = sessionStorage.getItem("user_type");
                    activityArgs.reg_date = sessionStorage.getItem("reg_date");
                    activityArgs.registration_status = sessionStorage.getItem("registration_status");
                    activityArgs.age_group = sessionStorage.getItem("age_group");
                    activityArgs.profile_country = sessionStorage.getItem("profile_country");
                    activityArgs.profile_state = sessionStorage.getItem("profile_state");
                    activityArgs.profile_city = sessionStorage.getItem("profile_city");
                    activityArgs.default_edition = sessionStorage.getItem("default_edition");
                    activityArgs.reg_publication = sessionStorage.getItem("reg_publication");
                    activityArgs.sessionid = sessionStorage.getItem("session");
                    if (activityArgs.eventname != "Forgot password") {
                        activityArgs.emailid = sessionStorage.getItem("emailid");
                    }
                    activityArgs.userid = sessionStorage.getItem("userid");

                    if (typeof currenteditiondate !== 'undefined') {

                        currenteditiondate = currenteditiondate.split("/").reverse().join("-");
                        activityArgs.Edition_date = currenteditiondate;
                    }

                    if (activityArgs.userid == 'null') {

                        activityArgs.userid = null;
                    }

                    if (activityArgs.emailid == 'null') {

                        activityArgs.emailid = null;
                    }

                    if (activityArgs.sessionid == 'null') {

                        activityArgs.sessionid = null;
                    }
                    
                    SAMConfig["insertDB"] = baseUrl + "api/epaperlogActivity";

                    $.ajax({
                        url: window.SAMConfig["insertDB"],
                        type: "POST",
                        async: true,
                        crossDomain: true,
                        dataType: "json",
                        contentType: "application/json",
                        data: JSON.stringify(activityArgs),
                        success: function (data) {
                            console.log(data);
                            //alert("Successfully inserted activity log data: " + data.Message);
                        },
                        error: function (qXHR, textStatus, errorThrown) {
                            console.log(qXHR);
							console.log("Error thrown from SAM API: "+errorThrown);
                            //alert("Could not insert data into DB. Server returned an error. Please try again!");
                        },
                    });
                }
            }
        }
    }
    catch (err) {
        console.log("Error in SAM event : processInsertDataRequest: "+err); 
    } 
}

function SAM_Registration(eventname, status, errortype, url, mailid, reg_mode, user_type, Reg_date, Registration_status, Age_group, Profile_country, Profile_state, Profile_city, default_edition, Reg_publication, errortype) {
    var SAM_Variables = {};
    try { 
        SAM_Variables.eventname = eventname;
        SAM_Variables.status = status;
        //SAM_Variables.ip = sessionStorage.getItem('currentip');
        SAM_Variables.webpage = url;
        //SAM_Variables.APIKey = sessionStorage.getItem('APIKey');
        SAM_Variables.emailid = mailid;  
        SAM_Variables.reg_mode = reg_mode;  
        SAM_Variables.user_type = user_type;  
        SAM_Variables.Reg_date = Reg_date;  
        SAM_Variables.Registration_status = Registration_status;  
        SAM_Variables.Age_group = Age_group;  
        SAM_Variables.Profile_country = Profile_country;  
        SAM_Variables.Profile_state = Profile_state; 
        SAM_Variables.default_edition = default_edition;
        SAM_Variables.Profile_city = Profile_city;
        SAM_Variables.Reg_publication = Reg_publication;
        //Send to our function for processing for a unknown visitor            
        processInsertDataRequest(SAM_Variables); 
    }
    catch (err) {
        console.log("Error in SAM event : SAM_Registation: "+err);
    }
}

function SAM_Login(eventname, status, errortype, url, emailid, Login_mode, session, userid) {
    var SAM_Variables = {};
    try {
        SAM_Variables.eventname = eventname;
        SAM_Variables.status = status;
        SAM_Variables.ip = sessionStorage.getItem('currentip');
        SAM_Variables.webpage = url;
        SAM_Variables.APIKey = sessionStorage.getItem('APIKey');        
        SAM_Variables.emailid = emailid;
        //SAM_Variables.Login_mode = Login_mode;
        SAM_Variables.sessionid = session;
        SAM_Variables.userid = userid;
        sessionStorage.setItem("Login_mode", Login_mode);
        sessionStorage.setItem("session", session);
        SAM_Variables.Login_mode = "Normal Login";
        //Send to our function for processing for a unknown visitor            
        processInsertDataRequest(SAM_Variables);
    }
    catch (err) {
        console.log("Error in SAM event : SAM_Login "+err);
    }
   
}

function SAM_View(SAM_Variables) {
    try {        
        processInsertDataRequest(SAM_Variables); 
        GA_Call(SAM_Variables);
    }
    catch (err) {
        console.log("Error in SAM event : SAM_View: "+err);
    }
}

function GA_Call() {
    if (SAM_Variables.AddtoGA == "1") {
        if (SAM_Variables.eventname == "Article View") {
            if (SAM_Variables.IsMobile)
                AddtoGAArt("M/" + SAM_Variables.edition, SAM_Variables.Edition_date, SAM_Variables.Pgname, SAM_Variables.contentID, SAM_Variables.gaEvent, SAM_Variables.GA_Objectype)
            else
                AddtoGAArt(SAM_Variables.edition, SAM_Variables.Edition_date, SAM_Variables.Pgname, SAM_Variables.contentID, SAM_Variables.gaEvent, SAM_Variables.GA_Objectype)
        }
        else {
            if (SAM_Variables.IsMobile)
                AddtoGA("M/" + SAM_Variables.edition, SAM_Variables.Edition_date, SAM_Variables.pagenum, SAM_Variables.gaEvent);
            else
                AddtoGA(SAM_Variables.edition, SAM_Variables.Edition_date, SAM_Variables.pagenum, SAM_Variables.gaEvent);
        }
    }
    else {
        //console.log("AddtoGA is disable");
    }
        
}

function SAM_Pageload() {
   // alert("Page load");
    try {
        var Url = window.location.href.toLowerCase();
        if (Url.indexOf('mindex') > 0) {
            SAM_Variables.eventname = "Index Page Visited";
            SAM_Variables.Pageview = "Thumb";
            SAM_Variables.contentsource = "current";
            var sessionStartTime = new Date();
            sessionStorage.setItem("sessionStartTime", sessionStartTime);
        }
        if (Url.indexOf('index') > 0) {
            SAM_Variables.eventname = "Index Page Visited";
            SAM_Variables.Pageview = "Thumb";
            var sessionStartTime = new Date();
            sessionStorage.setItem("sessionStartTime", sessionStartTime);
        }
        if (Url.indexOf('articleview') > 0) {
            SAM_Variables.eventname = "Article Page Visited";
            SAM_Variables.Pageview = "List";
            //Session start here in JS
            var sessionStartTime = new Date();
            sessionStorage.setItem("sessionStartTime", sessionStartTime);
        }
        if (Url.indexOf('fullview') > 0) {
            SAM_Variables.eventname = "Fullview Page Visited";
            SAM_Variables.Pageview = "Full";
            var sessionStartTime = new Date();
            sessionStorage.setItem("sessionStartTime", sessionStartTime);
        }
        if (Url.indexOf('activity') > 0)
            SAM_Variables.eventname = "Activity Page Visited";
        if (Url.indexOf('contact') > 0)
            SAM_Variables.eventname = "Contact Page Visited";
        if (Url.indexOf('faq') > 0)
            SAM_Variables.eventname = "Faq Page Visited";
        if (Url.indexOf('termsandcondition') > 0)
            SAM_Variables.eventname = "Termsandcondition Page Visited";
        if (Url.indexOf('mysubscription') > 0)
            SAM_Variables.eventname = "Mysubscription Page Visited";
        if (Url.indexOf('mytransaction') > 0)
            SAM_Variables.eventname = "Mytransaction Page Visited";
        if (Url.indexOf('myfavourite') > 0)
            SAM_Variables.eventname = "Myfavourite Page Visited";
        if (Url.indexOf('myprofile') > 0)
            SAM_Variables.eventname = "MyProfile Page Visited";
        if (Url.indexOf('subscription') > 0)
            SAM_Variables.eventname = "Subscription Page Visited";
        if (Url.indexOf('validate') > 0)
            SAM_Variables.eventname = "Validate Page Visited";
        //Url.indexOf('validate') == -1 && Url.indexOf('termsandcondition') == -1 && Url.indexOf('package') == -1 && Url.indexOf('privacypolicy') == -1) 

        SAM_Variables.status = "success";
        SAM_Variables.webpage = window.location.href;
        SAM_Variables.Publication = PublicationNameConfig;
        SAM_View(SAM_Variables);
    }
    catch (err)
    {
        console.log("Error in SAM_Pageload "+err);
    }

}

//Capture date and time for each event here:
function getDateTime() {
    var dateTimeObj = {};
    var now = new Date();
    var year = now.getFullYear();
    var month = now.getMonth() + 1;
    var datenumber = now.getDate();
    var day = now.getDay();
    var hour = now.getHours();
    var minute = now.getMinutes();
    var second = now.getSeconds();
    if (month.toString().length == 1) {
        month = '0' + month;
    }
    if (datenumber.toString().length == 1) {
        datenumber = '0' + datenumber;
    }
    if (hour.toString().length == 1) {
        hour = '0' + hour;
    }
    if (minute.toString().length == 1) {
        minute = '0' + minute;
    }
    if (second.toString().length == 1) {
        second = '0' + second;
    }
    var dateTime = year + '/' + month + '/' + datenumber + ' ' + hour + ':' + minute + ':' + second;
    var dateOnly = month + '/' + datenumber + '/' + year;
    dateTimeObj.dateTime = dateTime;
    dateTimeObj.month = month;
    dateTimeObj.day = day;
    dateTimeObj.datenumber = datenumber;
    dateTimeObj.hour = hour;
    dateTimeObj.minute = minute;
    dateTimeObj.second = second;
    dateTimeObj.date = dateOnly;
    return dateTimeObj;
}

function getCurrentFinancialYear() {
    var fiscalyear = "";
    var today = new Date();
    if ((today.getMonth() + 1) <= 3) {
        fiscalyear = (today.getFullYear() - 1) + "-" + today.getFullYear()
    } else {
        fiscalyear = today.getFullYear() + "-" + (today.getFullYear() + 1)
    }
    return fiscalyear
}

function quarter_of_the_year() {
    var today = new Date();
    var month = today.getMonth() + 1;
    return "Q" + (Math.ceil(month / 3));
}

function getWeekOfMonth() {
    var today = new Date();
    let adjustedDate = today.getDate() + today.getDay();
    let prefixes = ['0', '1', '2', '3', '4', '5'];
    return (parseInt(prefixes[0 | adjustedDate / 7]));
}

function stringToDate(_date, _format, _delimiter) {
    var formatLowerCase = _format.toLowerCase();
    var formatItems = formatLowerCase.split(_delimiter);
    var dateItems = _date.split(_delimiter);
    var monthIndex = formatItems.indexOf("mm");
    var dayIndex = formatItems.indexOf("dd");
    var yearIndex = formatItems.indexOf("yyyy");
    var month = parseInt(dateItems[monthIndex]);
    month -= 1;
    var formatedDate = new Date(dateItems[yearIndex], month, dateItems[dayIndex]);
    return formatedDate;
}
