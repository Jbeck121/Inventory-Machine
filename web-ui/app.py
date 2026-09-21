from flask import Flask, render_template, request

ITEMS = [
    {"name": "Cordless drill", "category": "tools", "location": "garage"},
    {"name": "Claw hammer", "category": "tools", "location": "garage"},
    {"name": "Ceramic mug", "category": "kitchen", "location": "kitchen"},
    {"name": "Cast iron skillet", "category": "kitchen", "location": "kitchen"},
    {"name": "USB cable", "category": "electronics", "location": "office"},
]

category_set = set()
location_set = set()
for item in ITEMS:
    category_set.add(item["category"])
    location_set.add(item["location"])

categories = sorted(category_set)
locations = sorted(location_set)
#Test items and categories

app = Flask(__name__)
#__name__ tells flask where the file lives 

@app.route('/')
#this registers this function as a handler for a specific URL

def home():
#this function is used to return an actual response sent to the browser 
    search_term = request.args.get("search", "")
    location = request.args.get("location", "")
    category = request.args.get("category","")
    #gets the argument set by the form with the search name, second stirng is a fallback

    results = []
    
    if search_term:
        for item in ITEMS:
            item_name_lowercase = item["name"].lower()
            
            if search_term.lower() in item_name_lowercase:
                results.append(item)
    elif category or location:
        for item in ITEMS:
            matches_category = (not category) or (item["category"] == category)
            matches_location = (not location) or (item["location"] == location)
            if matches_category and matches_location:
                results.append(item)

    return render_template(
        "home.html",
        search_term = search_term,
        category=category,
        location = location,
        categories = categories,
        locations = locations,
        results=results)


if __name__ == "__main__":
    app.run(debug=True, port=5050)