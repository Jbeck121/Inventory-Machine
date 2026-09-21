from flask import Flask, render_template, request

ITEMS = [
    {"name": "Cordless drill", "category": "tools"},
    {"name": "Claw hammer", "category": "tools"},
    {"name": "Ceramic mug", "category": "kitchen"},
    {"name": "Cast iron skillet", "category": "kitchen"},
    {"name": "USB cable", "category": "electronics"},
]
#Test items and categories

app = Flask(__name__)
#__name__ tells flask where the file lives 

@app.route('/')
#this registers this function as a handler for a specific URL

def home():
#this function is used to return an actual response sent to the browser 
    search_term = request.args.get("search", "")
    category = request.args.get("category", "")
    #gets the argument set by the form with the search name, second stirng is a fallback

    results = []
    if search_term:

        for item in ITEMS:
            item_name_lowercase = item["name"].lower()
            
            if search_term.lower() in item_name_lowercase:
                results.append(item)
    elif category:
        for item in ITEMS:
            if item["category"] == category:
                results.append(item)

    
    if(len(results) == 0):
        return render_template(
            "home.html",
            search_term = search_term,
            category=category,
            categories =["tools", "kitchen", "electronics", "clothing"],
            results=[])
    
    return render_template(
        "home.html",
        search_term = search_term,
        category=category,
        categories =["tools", "kitchen", "electronics", "clothing"],
        results=results)


if __name__ == "__main__":
    app.run(debug=True, port=5050)