git_pvt() {
    git config --global user.name "Santosh Parashetti"
    git config --global user.email "santu.parashetti@gmail.com"
    echo "✅ Switched to Personal Git account"
}

git_office() {
    git config --global user.name "Santosh Parashetti"
    git config --global user.email "santosh.parashetti@smarthub.ai"
    echo "🏢 Switched to Office Git account"
}

git_who() {
    echo "Current Git identity:"
    git config --global --get user.name
    git config --global --get user.email
}