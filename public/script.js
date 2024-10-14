document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('tessbot-form');

    form.addEventListener('submit', function(event) {
        event.preventDefault();
    
        const accessToken = document.getElementById('access-token').value.trim();
        const unitId = document.getElementById('unit-id').value.trim();
    
        if (accessToken === '' || unitId === '') {
            alert('Please enter both Access Token and Unit ID.');
            return;
        }
    
        fetch('/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ accessToken, unitId })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.blob();  // Get the response as a Blob (file data)
        })
        .then(blob => {
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'quizzes.txt';  // Default download name
            document.body.appendChild(a);
            a.click();
            a.remove();
        })
        .catch(error => {
            console.error('Fetch error:', error);
            alert('Failed to trigger main function in Express.js. Please try again later.');
        });
    });
    
});
