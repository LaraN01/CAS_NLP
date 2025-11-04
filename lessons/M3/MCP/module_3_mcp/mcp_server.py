import os
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP
import sqlite3

"""
Updated mcp_server.py script with more tools and a resource call.
Tools added:
- current_datetime: Returns the current date and time.
- get_weather: Fetches current weather information for a given city from weather.com.

Resource added:
- cas_nlp_info: Provides information about the CAS Natural Language Processing program from the University of Bern by fetching data from the official website.
"""

# 1. Create an MCP server instance
mcp = FastMCP("MCP server example]")

# 2. Define a tool using the @mcp.tool() decorator. What else is there beside @mcp.tool? define other tools or useful "stuff" to expose to the LLM
## mcp.resource() to define resources (but this didn't really work!)
## mcp.event() to define event handlers
@mcp.tool()
def calculator(num1: float, num2: float, operator: str) -> float:
    """
    A simple calculator function that performs basic arithmetic operations.

    Parameters
    ----------
    num1 : float
        The first number in the calculation.
    num2 : float
        The second number in the calculation.
    operator : str
        The arithmetic operation to perform. 
        Supported values are:
        - "+" : addition
        - "-" : subtraction
        - "*" : multiplication
        - "/" : division

    Returns
    -------
    float
        The result of the calculation.

    Raises
    ------
    ValueError
        If the operator is not supported or if division by zero is attempted.
    """
    if operator == "+":
        return num1 + num2
    elif operator == "-":
        return num1 - num2
    elif operator == "*":
        return num1 * num2
    elif operator == "/":
        if num2 == 0:
            raise ValueError("Division by zero is not allowed.")
        return num1 / num2
    else:
        raise ValueError(f"Unsupported operator: {operator}. Use one of '+', '-', '*', '/'.")


@mcp.tool()
def current_datetime() -> str:
    """
    Returns the current date and time in the system's local timezone.

    Returns
    -------
    str
        The current date and time in ISO 8601 format (YYYY-MM-DD HH:MM:SS).
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@mcp.tool()
def get_weather(city: str) -> str:
    """
    Fetches current weather information for a given city using Open-Meteo API.
    If multiple cities with the same name exist, returns weather for all of them.

    Parameters
    ----------
    city : str
        The name of the city to get weather information for.

    Returns
    -------
    str
        Weather information for the city/cities, including temperature, conditions,
        and location details. If multiple cities match, returns data for all.

    Raises
    ------
    Exception
        If the weather data cannot be fetched or parsed.
    """
    try:
        # Step 1: Use Open-Meteo's geocoding API to find the city
        geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
        geocoding_params = {
            'name': city,
            'count': 5,  # Get up to 5 matches
            'language': 'en',
            'format': 'json'
        }

        geo_response = requests.get(geocoding_url, params=geocoding_params, timeout=10)
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        if 'results' not in geo_data or not geo_data['results']:
            return f"No weather data found for city: {city}"

        locations = geo_data['results']
        weather_results = []

        # Step 2: For each location, fetch weather data
        for location in locations[:5]:  # Limit to first 5 matches
            try:
                latitude = location['latitude']
                longitude = location['longitude']
                city_name = location['name']
                country = location.get('country', '')
                admin1 = location.get('admin1', '')  # State/province

                # Construct location string
                location_str = f"{city_name}"
                if admin1:
                    location_str += f", {admin1}"
                if country:
                    location_str += f", {country}"

                # Fetch current weather data from Open-Meteo
                weather_url = "https://api.open-meteo.com/v1/forecast"
                weather_params = {
                    'latitude': latitude,
                    'longitude': longitude,
                    'current': 'temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m',
                    'temperature_unit': 'celsius',
                    'wind_speed_unit': 'kmh',
                    'timezone': 'auto'
                }

                weather_response = requests.get(weather_url, params=weather_params, timeout=10)
                weather_response.raise_for_status()
                weather_data = weather_response.json()

                current = weather_data['current']

                # Map WMO weather codes to descriptions
                weather_codes = {
                    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                    45: "Foggy", 48: "Depositing rime fog",
                    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
                    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
                    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
                    77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers",
                    82: "Violent rain showers", 85: "Slight snow showers", 86: "Heavy snow showers",
                    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
                }

                weather_code = current.get('weather_code', 0)
                conditions = weather_codes.get(weather_code, "Unknown")

                result = f"Location: {location_str}\n"
                result += f"Temperature: {current['temperature_2m']}°C\n"
                result += f"Feels like: {current['apparent_temperature']}°C\n"
                result += f"Conditions: {conditions}\n"
                result += f"Humidity: {current['relative_humidity_2m']}%\n"
                result += f"Wind speed: {current['wind_speed_10m']} km/h\n"
                result += f"Precipitation: {current['precipitation']} mm\n"

                weather_results.append(result)

            except Exception as e:
                # If we can't get weather for this specific location, skip it
                continue

        if not weather_results:
            return f"Could not retrieve weather data for: {city}"

        if len(weather_results) > 1:
            return f"Found {len(weather_results)} cities named '{city}':\n\n" + "\n---\n".join(weather_results)
        else:
            return weather_results[0]

    except requests.RequestException as e:
        raise Exception(f"Failed to fetch weather data: {str(e)}")
    except Exception as e:
        raise Exception(f"Error processing weather data: {str(e)}")


@mcp.tool()
def get_cas_nlp_info() -> str:
    """
    Fetches information about the CAS Natural Language Processing program
    at the University of Bern, including topics, structure, and course details.
    Use this tool when users ask about the CAS NLP program at University of Bern.

    Returns
    -------
    str
        Detailed information about the CAS NLP program from the University of Bern,
        including course topics, structure, prerequisites, and other program details.

    Raises
    ------
    Exception
        If the website cannot be accessed or parsed.
    """
    url = "https://www.unibe.ch/continuing_education_programs/cas_natural_language_processing/index_eng.html"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract the main content
        main_content = soup.find('div', class_='main-content') or soup.find('main') or soup.body

        if main_content:
            # Get text content, removing excessive whitespace
            text = main_content.get_text(separator='\n', strip=True)
            # Clean up multiple newlines
            text = '\n'.join(line for line in text.split('\n') if line.strip())
            return text
        else:
            return "Could not parse the webpage content."

    except requests.RequestException as e:
        raise Exception(f"Failed to fetch CAS NLP information: {str(e)}")



@mcp.tool()
def get_module_info(module_code: str = None) -> str:
    """
    Retrieves CAS NLP module information from the local database.

    Parameters
    ----------
    module_code : str, optional
        The module code (e.g., M1, M2). If not provided, lists all modules.

    Returns
    -------
    str
        A formatted string containing module information.
    """
    try:
        conn = sqlite3.connect("cas_nlp.db")
        cursor = conn.cursor()

        if module_code:
            cursor.execute("SELECT module_code, title, date, time, location, lecturers, comments, project_info FROM modules WHERE module_code LIKE ?", (f"%{module_code}%",))
        else:
            cursor.execute("SELECT module_code, title, date, time, location, lecturers, comments, project_info FROM modules")

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return f"No module found for '{module_code}'" if module_code else "No modules available."

        result = []
        for code, title, date, time, loc, lect, com, proj in rows:
            entry = f"📘 {code}: {title}\n📅 {date}\n⏰ {time}\n📍 {loc}\n👨‍🏫 {lect}\n💬 {com}\n🧩 {proj}\n"
            result.append(entry)

        return "\n----------------------\n".join(result)

    except Exception as e:
        return f"Database error: {e}"


# 3. Main entry point to run the server
if __name__ == "__main__":
    print("--- MCP Tool Server starting over stdio... ---")
    # This runs the server, communicating over standard input/output
    # It will wait for a client to connect.
    mcp.run(transport="stdio")
# if __name__ == "__main__":
#     print("Manual MCP Tool Tests")

    # # Call your tools directly
    # print("\n🧮 Calculator:")
    # print(calculator(5, 3, "+"))

    # print("\n📅 Current datetime:")
    # print(current_datetime())

    # print("\n🌤 Weather:")
    # print(get_weather("Bern"))

    # print("\n🎓 CAS NLP Info:")
    # print(get_cas_nlp_info()[:300], "...")  # print first 300 chars only

    # print("\n📘 Module info:")
    # print(get_module_info("M3"))