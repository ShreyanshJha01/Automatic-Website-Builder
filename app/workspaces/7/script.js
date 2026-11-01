// Mobile menu functionality
document.addEventListener('DOMContentLoaded', function() {
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const mobileMenu = document.getElementById('mobile-menu');
    
    // Toggle mobile menu
    mobileMenuBtn.addEventListener('click', function() {
        mobileMenu.classList.toggle('hidden');
        
        // Change icon based on menu state
        const icon = mobileMenuBtn.querySelector('svg');
        if (mobileMenu.classList.contains('hidden')) {
            icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path>';
        } else {
            icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>';
        }
    });
    
    // Close mobile menu when clicking on a link
    const mobileLinks = mobileMenu.querySelectorAll('a');
    mobileLinks.forEach(link => {
        link.addEventListener('click', function() {
            mobileMenu.classList.add('hidden');
            // Reset icon
            const icon = mobileMenuBtn.querySelector('svg');
            icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path>';
        });
    });
    
    // Close mobile menu when clicking outside
    document.addEventListener('click', function(event) {
        const isClickInside = mobileMenuBtn.contains(event.target) || mobileMenu.contains(event.target);
        if (!isClickInside && !mobileMenu.classList.contains('hidden')) {
            mobileMenu.classList.add('hidden');
            const icon = mobileMenuBtn.querySelector('svg');
            icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path>';
        }
    });
    
    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
    
    // Add active state to navigation links based on scroll position
    const sections = document.querySelectorAll('section[id]');
    const navLinks = document.querySelectorAll('.nav-link');
    
    function updateActiveNav() {
        let current = '';
        sections.forEach(section => {
            const sectionTop = section.offsetTop;
            const sectionHeight = section.clientHeight;
            if (window.pageYOffset >= sectionTop - 100) {
                current = section.getAttribute('id');
            }
        });
        
        navLinks.forEach(link => {
            link.classList.remove('text-blue-600', 'font-semibold');
            link.classList.add('text-gray-600', 'font-medium');
            if (link.getAttribute('href') === `#${current}`) {
                link.classList.remove('text-gray-600', 'font-medium');
                link.classList.add('text-blue-600', 'font-semibold');
            }
        });
    }
    
    window.addEventListener('scroll', updateActiveNav);
    updateActiveNav(); // Initial call
    
    // Feature card hover effect enhancement
    const featureCards = document.querySelectorAll('.feature-card');
    featureCards.forEach(card => {
        card.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-5px)';
            this.style.transition = 'transform 0.3s ease';
        });
        
        card.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0)';
        });
    });
    
    // Search functionality (placeholder)
    const searchInput = document.createElement('input');
    searchInput.setAttribute('type', 'text');
    searchInput.setAttribute('id', 'search-input');
    searchInput.setAttribute('placeholder', 'Search...');
    searchInput.className = 'hidden w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent';
    
    // Add search to header if needed
    const headerActions = document.querySelector('.ml-10');
    if (headerActions) {
        const searchBtn = document.createElement('button');
        searchBtn.innerHTML = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>';
        searchBtn.className = 'text-gray-600 hover:text-blue-600 p-2 rounded-lg hover:bg-gray-100 transition-colors';
        searchBtn.addEventListener('click', function() {
            // Toggle search input visibility
            if (searchInput.classList.contains('hidden')) {
                searchInput.classList.remove('hidden');
                searchInput.focus();
            } else {
                searchInput.classList.add('hidden');
            }
        });
        
        headerActions.appendChild(searchBtn);
        headerActions.appendChild(searchInput);
    }
    
    // Add loading state to all buttons and links
    const interactiveElements = document.querySelectorAll('a, button, [role="button"]');
    interactiveElements.forEach(element => {
        element.addEventListener('click', function(e) {
            // Add loading class after a small delay to avoid immediate loading on fast clicks
            setTimeout(() => {
                this.classList.add('loading');
            }, 100);
            
            // Remove loading class after interaction
            setTimeout(() => {
                this.classList.remove('loading');
            }, 2000);
        });
    });
    
    // Add copy to clipboard functionality for phone/email in footer
    const footerContacts = document.querySelectorAll('[data-copy]');
    footerContacts.forEach(element => {
        element.style.cursor = 'pointer';
        element.title = 'Click to copy';
        element.addEventListener('click', function() {
            const text = this.textContent.trim();
            navigator.clipboard.writeText(text).then(() => {
                // Show temporary success message
                const originalText = this.textContent;
                this.textContent = 'Copied!';
                this.classList.add('text-green-400');
                
                setTimeout(() => {
                    this.textContent = originalText;
                    this.classList.remove('text-green-400');
                }, 2000);
            }).catch(err => {
                console.error('Failed to copy: ', err);
            });
        });
    });
});