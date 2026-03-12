# Frontend Registration Form Update Guide

## Overview
The backend registration endpoint now accepts `country_code` and `phone_number` fields. These should be combined on the frontend before sending to the backend.

## Backend Changes Summary
- **Schema Updated**: `schemas/register.py` now includes `country_code` and `phone_number` fields
- **Service Updated**: `services/register_service.py` combines them as `{country_code}{phone_number}` and stores in `phone_number` field
- **Endpoint**: `POST /api/auth/register` (or your registration endpoint)

## Frontend Implementation

### 1. Update Registration Form Component

Update your `Register.jsx` or `Register.tsx` component to include country code and phone number fields:

```jsx
import React, { useState } from 'react';
import axios from 'axios';

const Register = () => {
  const [formData, setFormData] = useState({
    full_name: '',
    email: '',
    dob: '',
    gender: '',
    password: '',
    country_code: '+1',  // Default to +1 (US)
    phone_number: ''
  });

  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // Common country codes
  const countryCodes = [
    { code: '+1', country: 'United States' },
    { code: '+44', country: 'United Kingdom' },
    { code: '+91', country: 'India' },
    { code: '+86', country: 'China' },
    { code: '+81', country: 'Japan' },
    { code: '+33', country: 'France' },
    { code: '+49', country: 'Germany' },
    { code: '+39', country: 'Italy' },
    { code: '+34', country: 'Spain' },
    { code: '+61', country: 'Australia' },
    { code: '+64', country: 'New Zealand' },
    { code: '+27', country: 'South Africa' },
    { code: '+55', country: 'Brazil' },
    { code: '+52', country: 'Mexico' },
    { code: '+1-876', country: 'Jamaica' },
    // Add more as needed
  ];

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      // Validate phone number
      if (!formData.phone_number.trim()) {
        setError('Phone number is required');
        setLoading(false);
        return;
      }

      // Send registration request
      const response = await axios.post(
        'http://localhost:8000/api/auth/register',  // Update with your backend URL
        {
          full_name: formData.full_name,
          email: formData.email,
          dob: formData.dob,
          gender: formData.gender,
          password: formData.password,
          country_code: formData.country_code,
          phone_number: formData.phone_number
        },
        {
          withCredentials: true  // Include cookies if using cookie-based auth
        }
      );

      // Handle successful registration
      console.log('Registration successful:', response.data);
      // Redirect to login or dashboard
      // window.location.href = '/login';
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed. Please try again.');
      console.error('Registration error:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="register-container">
      <h2>Create Account</h2>
      
      {error && <div className="error-message">{error}</div>}

      <form onSubmit={handleSubmit}>
        {/* Full Name */}
        <div className="form-group">
          <label htmlFor="full_name">Full Name</label>
          <input
            type="text"
            id="full_name"
            name="full_name"
            value={formData.full_name}
            onChange={handleInputChange}
            required
            placeholder="John Doe"
          />
        </div>

        {/* Email */}
        <div className="form-group">
          <label htmlFor="email">Email</label>
          <input
            type="email"
            id="email"
            name="email"
            value={formData.email}
            onChange={handleInputChange}
            required
            placeholder="john@example.com"
          />
        </div>

        {/* Date of Birth */}
        <div className="form-group">
          <label htmlFor="dob">Date of Birth</label>
          <input
            type="date"
            id="dob"
            name="dob"
            value={formData.dob}
            onChange={handleInputChange}
            required
          />
        </div>

        {/* Gender */}
        <div className="form-group">
          <label htmlFor="gender">Gender</label>
          <select
            id="gender"
            name="gender"
            value={formData.gender}
            onChange={handleInputChange}
            required
          >
            <option value="">Select Gender</option>
            <option value="Male">Male</option>
            <option value="Female">Female</option>
            <option value="Other">Other</option>
          </select>
        </div>

        {/* Country Code + Phone Number */}
        <div className="form-group phone-group">
          <label>Phone Number</label>
          <div className="phone-input-wrapper">
            <select
              name="country_code"
              value={formData.country_code}
              onChange={handleInputChange}
              className="country-code-select"
            >
              {countryCodes.map(({ code, country }) => (
                <option key={code} value={code}>
                  {country} ({code})
                </option>
              ))}
            </select>
            <input
              type="tel"
              name="phone_number"
              value={formData.phone_number}
              onChange={handleInputChange}
              required
              placeholder="2025551234"
              className="phone-number-input"
            />
          </div>
        </div>

        {/* Password */}
        <div className="form-group">
          <label htmlFor="password">Password</label>
          <input
            type="password"
            id="password"
            name="password"
            value={formData.password}
            onChange={handleInputChange}
            required
            placeholder="Enter password"
          />
        </div>

        {/* Submit Button */}
        <button 
          type="submit" 
          disabled={loading}
          className="submit-button"
        >
          {loading ? 'Creating Account...' : 'Register'}
        </button>
      </form>

      <p className="login-link">
        Already have an account? <a href="/login">Login here</a>
      </p>
    </div>
  );
};

export default Register;
```

### 2. Add Styling (CSS)

```css
.register-container {
  max-width: 500px;
  margin: 50px auto;
  padding: 30px;
  border: 1px solid #ddd;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}

.register-container h2 {
  text-align: center;
  margin-bottom: 30px;
  color: #333;
}

.error-message {
  background-color: #f8d7da;
  color: #721c24;
  padding: 12px;
  border-radius: 4px;
  margin-bottom: 20px;
  border: 1px solid #f5c6cb;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 500;
  color: #333;
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
  font-family: inherit;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: #007bff;
  box-shadow: 0 0 5px rgba(0, 123, 255, 0.25);
}

/* Phone Number Group Styling */
.phone-group label {
  margin-bottom: 8px;
}

.phone-input-wrapper {
  display: flex;
  gap: 10px;
}

.country-code-select {
  flex: 0 0 150px;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.phone-number-input {
  flex: 1;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.submit-button {
  width: 100%;
  padding: 12px;
  background-color: #007bff;
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.3s;
}

.submit-button:hover:not(:disabled) {
  background-color: #0056b3;
}

.submit-button:disabled {
  background-color: #6c757d;
  cursor: not-allowed;
}

.login-link {
  text-align: center;
  margin-top: 20px;
  color: #666;
}

.login-link a {
  color: #007bff;
  text-decoration: none;
}

.login-link a:hover {
  text-decoration: underline;
}
```

### 3. Alternative: Using React Hook Form (Recommended for larger forms)

```jsx
import React from 'react';
import { useForm, Controller } from 'react-hook-form';
import axios from 'axios';

const RegisterWithHookForm = () => {
  const { control, handleSubmit, formState: { errors, isSubmitting } } = useForm({
    defaultValues: {
      full_name: '',
      email: '',
      dob: '',
      gender: '',
      password: '',
      country_code: '+1',
      phone_number: ''
    }
  });

  const countryCodes = [
    { code: '+1', country: 'United States' },
    { code: '+44', country: 'United Kingdom' },
    { code: '+91', country: 'India' },
    // ... more codes
  ];

  const onSubmit = async (data) => {
    try {
      const response = await axios.post(
        'http://localhost:8000/api/auth/register',
        data,
        { withCredentials: true }
      );
      console.log('Registration successful:', response.data);
      // Redirect to login
    } catch (error) {
      console.error('Registration error:', error.response?.data);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      {/* Full Name */}
      <Controller
        name="full_name"
        control={control}
        rules={{ required: 'Full name is required' }}
        render={({ field }) => (
          <div className="form-group">
            <label>Full Name</label>
            <input {...field} type="text" placeholder="John Doe" />
            {errors.full_name && <span className="error">{errors.full_name.message}</span>}
          </div>
        )}
      />

      {/* Email */}
      <Controller
        name="email"
        control={control}
        rules={{ 
          required: 'Email is required',
          pattern: { value: /^[^\s@]+@[^\s@]+\.[^\s@]+$/, message: 'Invalid email' }
        }}
        render={({ field }) => (
          <div className="form-group">
            <label>Email</label>
            <input {...field} type="email" placeholder="john@example.com" />
            {errors.email && <span className="error">{errors.email.message}</span>}
          </div>
        )}
      />

      {/* Date of Birth */}
      <Controller
        name="dob"
        control={control}
        rules={{ required: 'Date of birth is required' }}
        render={({ field }) => (
          <div className="form-group">
            <label>Date of Birth</label>
            <input {...field} type="date" />
            {errors.dob && <span className="error">{errors.dob.message}</span>}
          </div>
        )}
      />

      {/* Gender */}
      <Controller
        name="gender"
        control={control}
        rules={{ required: 'Gender is required' }}
        render={({ field }) => (
          <div className="form-group">
            <label>Gender</label>
            <select {...field}>
              <option value="">Select Gender</option>
              <option value="Male">Male</option>
              <option value="Female">Female</option>
              <option value="Other">Other</option>
            </select>
            {errors.gender && <span className="error">{errors.gender.message}</span>}
          </div>
        )}
      />

      {/* Country Code */}
      <Controller
        name="country_code"
        control={control}
        render={({ field }) => (
          <div className="form-group">
            <label>Country Code</label>
            <select {...field} className="country-code-select">
              {countryCodes.map(({ code, country }) => (
                <option key={code} value={code}>
                  {country} ({code})
                </option>
              ))}
            </select>
          </div>
        )}
      />

      {/* Phone Number */}
      <Controller
        name="phone_number"
        control={control}
        rules={{ required: 'Phone number is required' }}
        render={({ field }) => (
          <div className="form-group">
            <label>Phone Number</label>
            <input {...field} type="tel" placeholder="2025551234" />
            {errors.phone_number && <span className="error">{errors.phone_number.message}</span>}
          </div>
        )}
      />

      {/* Password */}
      <Controller
        name="password"
        control={control}
        rules={{ required: 'Password is required' }}
        render={({ field }) => (
          <div className="form-group">
            <label>Password</label>
            <input {...field} type="password" placeholder="Enter password" />
            {errors.password && <span className="error">{errors.password.message}</span>}
          </div>
        )}
      />

      <button type="submit" disabled={isSubmitting} className="submit-button">
        {isSubmitting ? 'Creating Account...' : 'Register'}
      </button>
    </form>
  );
};

export default RegisterWithHookForm;
```

## Testing the Integration

### 1. Test with cURL
```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "John Doe",
    "email": "john@example.com",
    "dob": "1990-01-15",
    "gender": "Male",
    "password": "SecurePassword123",
    "country_code": "+1",
    "phone_number": "2025551234"
  }'
```

### 2. Expected Response
```json
{
  "id": 1,
  "full_name": "John Doe",
  "email": "john@example.com",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

### 3. Verify in Database
The phone number should be stored as: `+12025551234` (country_code + phone_number combined)

## Notes
- The backend automatically combines `country_code` and `phone_number` into a single field
- No separator is added between country code and phone number (e.g., `+12025551234`)
- Phone number validation should be done on the frontend for better UX
- Consider adding phone number formatting libraries like `libphonenumber-js` for validation
