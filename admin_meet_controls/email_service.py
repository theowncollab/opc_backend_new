import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

def get_email_template(subject, body_content):
    return {
        'subject_': subject,
        'body_': f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f4f4f4; color: #333333;">
            
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f4f4f4; padding: 40px 0;">
                <tr>
                    <td align="center">
                        
                        <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                            
                            <tr>
                                <td style="background-color: #000000; padding: 40px 30px; text-align: center;">
                                    
                                    <img src="https://code-hamster-rohit1008.github.io/image_repo/logo.png" 
                                         alt="OPC Logo" 
                                         width="150"
                                         style="display: inline-block; max-width: 100%; height: auto; margin-bottom: 20px;">
                                    <h1 style="color: #FFD700; margin: 0; font-size: 24px; letter-spacing: 1px; text-transform: uppercase;">OPC Security</h1>
                                </td>
                            </tr>

                            <tr>
                                <td style="padding: 40px 30px;">
                                    
                                    <!-- Dynamic Content Start -->
                                    <div style="font-size: 16px; line-height: 1.6; color: #333333;">
                                        {body_content.replace(chr(10), '<br>')}
                                    </div>
                                    <!-- Dynamic Content End -->
                                    
                                    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">

                                    <p style="margin: 0; font-size: 16px; font-weight: bold;">Best regards,</p>
                                    <p style="margin: 5px 0 0 0; font-size: 16px;">The OPC Team</p>
                                </td>
                            </tr>

                            <tr>
                                <td style="background-color: #333333; padding: 20px; text-align: center; font-size: 12px; color: #bbbbbb;">
                                    <p style="margin: 0;">&copy; 2025 OPC. All rights reserved.</p>
                                    <p style="margin: 5px 0 0 0;">Please do not reply to this automated message.</p>
                                </td>
                            </tr>
                        </table>

                    </td>
                </tr>
            </table>
        
        </body>
        </html>
        """
    }

def send_email_wrapper(to_email, subject, body):
    email_data = get_email_template(subject, body)
    
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASSWORD")
    
    if not sender_email or not sender_password:
        raise ValueError("EMAIL_USER and EMAIL_PASSWORD environment variables must be set")

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = email_data['subject_']

    msg.attach(MIMEText(email_data['body_'], 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
    except Exception as e:
        print(f"Error sending email: {e}")
        raise e
