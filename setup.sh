#!/bin/bash
set -e

# --- Prompt for basic information ---
read -p ">> What is the name of your new function (e.g., 'my-new-service')? " FUNCTION_NAME
read -p ">> Will this function connect to a database? (y/n) " WANTS_DATABASE

echo "------------------------------------------------------------------"
echo "Configuring project for function: ${FUNCTION_NAME}"
echo "------------------------------------------------------------------"

# --- Replace placeholder names in key files ---
# Using a generic placeholder like 'template-function-name' in your files
PLACEHOLDER="template-function-name"
# Mac users have a different sed syntax, this handles both
if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' "s/${PLACEHOLDER}/${FUNCTION_NAME}/g" func.yaml .github/workflows/deploy.yml README.md
else
    sed -i "s/${PLACEHOLDER}/${FUNCTION_NAME}/g" func.yaml .github/workflows/deploy.yml README.md
fi
echo "✅ Renamed function to '${FUNCTION_NAME}'."

# --- Handle optional features ---
if [[ "$WANTS_DATABASE" != "y" ]]; then
    echo "Removing database components..."

    # Remove database packages from requirements.txt
    sed -i '/# --- DB_DEPS_START ---/,/# --- DB_DEPS_END ---/d' requirements.txt
    echo "✅ Removed database dependencies."

    # Remove database logic from main.py
    sed -i '/# --- DB_LOGIC_START ---/,/# --- DB_LOGIC_END ---/d' main.py
    echo "✅ Removed database logic from main.py."

    # Remove database IAM policy from README.md
    sed -i '/<!-- DB_IAM_START -->/,/<!-- DB_IAM_END -->/d' README.md
    echo "✅ Removed database documentation from README."
else
    echo "✅ Keeping database components."
fi

# --- Final Cleanup ---
echo "Removing setup script..."
rm -- "$0"

echo "------------------------------------------------------------------"
echo "🚀 Project setup complete!"
echo "Next steps:"
echo "1. Create your dedicated IAM user and group in OCI."
echo "2. Update your GitHub repository secrets."
echo "3. Commit and push your changes to trigger the first deployment."
echo "------------------------------------------------------------------"