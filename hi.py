import tkinter as tk
from tkinter import filedialog, messagebox
import os

def merge_files():
    # Open file dialog to select multiple .txt files
    file_paths = filedialog.askopenfilenames(title="Select .txt files", filetypes=[("Text files", "*.txt")])
    
    if not file_paths:
        return

    merged_content = ""
    
    for file_path in file_paths:
        # Get the filename without the extension for the heading
        heading = os.path.splitext(os.path.basename(file_path))[0]
        merged_content += f"{heading}\n//\n"
        
        with open(file_path, 'r') as file:
            content = file.read()
            merged_content += content + "\n\n"

    # Save the merged content to a new file
    save_path = filedialog.asksaveasfilename(defaultextension=".txt", title="Save Merged File", filetypes=[("Text files", "*.txt")])
    
    if save_path:
        with open(save_path, 'w') as output_file:
            output_file.write(merged_content)
        
        messagebox.showinfo("Success", "Files merged successfully!")

# Create the main window
root = tk.Tk()
root.title("Text File Merger")
root.geometry("300x200")

# Create a button to merge files
merge_button = tk.Button(root, text="Merge .txt Files", command=merge_files)
merge_button.pack(expand=True)

# Start the GUI event loop
root.mainloop()
