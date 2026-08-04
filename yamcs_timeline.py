#!/usr/bin/env python3
"""
YAMCS Timeline Manager
Save and load YAMCS timeline views and bands.

Usage:
    # Save all timeline views to a file
    ./yamcs_timeline.py save timeline_backup.json
    
    # Load timeline views from a file
    ./yamcs_timeline.py load timeline_backup.json
    
    # List current timeline views
    ./yamcs_timeline.py list
    
    # Export to directory (creates separate JSON files per view)
    ./yamcs_timeline.py export timelines/
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests


class YAMCSTimelineManager:
    def __init__(self, instance="shire", base_url="http://localhost:8090"):
        self.instance = instance
        self.base_url = base_url
        self.api_base = f"{base_url}/api/timeline/{instance}"
    
    def get_all_views(self):
        """Get all timeline views"""
        r = requests.get(f"{self.api_base}/views")
        r.raise_for_status()
        return r.json()
    
    def get_all_bands(self):
        """Get all timeline bands"""
        r = requests.get(f"{self.api_base}/bands")
        r.raise_for_status()
        return r.json()
    
    def get_all_items(self, band_id=None):
        """Get all timeline items, optionally filtered by band"""
        params = {'source': 'rdb'}
        if band_id:
            params['band'] = band_id
        r = requests.get(f"{self.api_base}/items", params=params)
        r.raise_for_status()
        return r.json()
    
    def save_to_file(self, filename):
        """Save all timeline views, bands, and items to a JSON file"""
        views_data = self.get_all_views()
        bands_data = self.get_all_bands()
        items_data = self.get_all_items()
        
        # Combine into single export structure
        export_data = {
            'views': views_data.get('views', []),
            'bands': bands_data.get('bands', []),
            'items': items_data.get('items', [])
        }
        
        with open(filename, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        view_count = len(export_data['views'])
        band_count = len(export_data['bands'])
        item_count = len(export_data['items'])
        print(f"✓ Saved {view_count} view(s), {band_count} band(s), and {item_count} item(s) to {filename}")
        return export_data
    
    def load_from_file(self, filename):
        """Load timeline views, bands, and items from a JSON file and restore them"""
        with open(filename, 'r') as f:
            data = json.load(f)
        
        # Support different formats
        views = data.get('views', [])
        bands = data.get('bands', [])
        items = data.get('items', [])
        
        if not views and not bands and not items:
            print("No views, bands, or items found in file")
            return
        
        # Get existing views and bands to check for duplicates
        existing_views = self.get_all_views().get('views', [])
        existing_bands = self.get_all_bands().get('bands', [])
        
        # Create a mapping of old band IDs to new band IDs
        band_id_map = {}
        band_name_to_id = {}
        
        # Load bands first (views reference them by ID)
        if bands:
            print(f"Loading {len(bands)} band(s)...")
            for band in bands:
                old_band_id = band.get('id')
                band_name = band['name']
                
                # Delete existing band with same name
                for existing in existing_bands:
                    if existing['name'] == band_name:
                        print(f"  Deleting existing band: {band_name}")
                        try:
                            requests.delete(f"{self.api_base}/bands/{existing['id']}")
                        except:
                            pass
                
                new_band_id = self._restore_band_standalone(band)
                if old_band_id and new_band_id:
                    band_id_map[old_band_id] = new_band_id
                if new_band_id:
                    band_name_to_id[band_name] = new_band_id
        
        # Load views with band references
        if views:
            print(f"Loading {len(views)} view(s)...")
            for view in views:
                view_name = view['name']
                
                # Delete existing view with same name
                for existing in existing_views:
                    if existing['name'] == view_name:
                        print(f"  Deleting existing view: {view_name}")
                        try:
                            requests.delete(f"{self.api_base}/views/{existing['id']}")
                        except:
                            pass
                
                # Create view with band IDs
                view_bands = view.get('bands', [])
                band_ids = []
                
                # Map old band IDs to new ones, or look up by name
                for view_band in view_bands:
                    if isinstance(view_band, dict):
                        # Band object from nested structure
                        old_id = view_band.get('id')
                        band_name = view_band.get('name')
                        
                        # Try to find the new ID
                        new_id = band_id_map.get(old_id) or band_name_to_id.get(band_name)
                        if new_id:
                            band_ids.append(new_id)
                    elif isinstance(view_band, str):
                        # Already a band ID string
                        new_id = band_id_map.get(view_band)
                        if new_id:
                            band_ids.append(new_id)
                
                self._restore_view_with_bands(view_name, band_ids)
        
        if items:
            print(f"Loading {len(items)} timeline item(s)...")
            for item in items:
                self._restore_item(item, band_id_map)
        
        print(f"✓ Loaded {len(views)} view(s), {len(bands)} band(s), and {len(items)} item(s)")
    
    def _restore_view_only(self, view):
        """Restore a single view (without bands)"""
        view_name = view['name']
        view_payload = {'name': view_name}
        
        try:
            r = requests.post(f"{self.api_base}/views", json=view_payload)
            r.raise_for_status()
            new_view = r.json()
            print(f"  Created view: {view_name} (id: {new_view['id']})")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                print(f"  ⚠ View '{view_name}' may already exist, skipping...")
            else:
                print(f"  ✗ Error creating view '{view_name}': {e}")
    
    def _restore_view_with_bands(self, view_name, band_ids):
        """Restore a single view with band IDs"""
        view_payload = {
            'name': view_name,
            'bands': band_ids
        }
        
        try:
            r = requests.post(f"{self.api_base}/views", json=view_payload)
            r.raise_for_status()
            new_view = r.json()
            print(f"  Created view: {view_name} (id: {new_view['id']}) with {len(band_ids)} band(s)")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                print(f"  ⚠ View '{view_name}' may already exist, skipping...")
            else:
                print(f"  ✗ Error creating view '{view_name}': {e}")
    
    def _restore_band_standalone(self, band):
        """Restore a single band as a standalone entity, returns new band ID"""
        band_name = band['name']
        
        # Prepare band payload (exclude id and username since they will be auto-generated)
        band_payload = {
            'name': band_name,
            'shared': band.get('shared', True),
            'type': band['type'],
            'description': band.get('description', ''),
        }
        
        # Only add properties if they exist
        if 'properties' in band and band['properties']:
            band_payload['properties'] = band['properties']
        
        try:
            r = requests.post(f"{self.api_base}/bands", json=band_payload)
            r.raise_for_status()
            new_band = r.json()
            new_band_id = new_band.get('id')
            print(f"  Created band: {band_name} ({band['type']}, id: {new_band_id})")
            return new_band_id
        except requests.exceptions.HTTPError as e:
            print(f"  ✗ Error creating band '{band_name}': {e.response.text if hasattr(e, 'response') else e}")
            return None
    
    def _restore_item(self, item, band_id_map):
        """Restore a single timeline item"""
        item_name = item.get('name', 'Unnamed Item')
        old_band_id = item.get('groupId')  # groupId is the band ID
        
        # Map old band ID to new band ID
        new_band_id = band_id_map.get(old_band_id)
        if not new_band_id:
            print(f"    ⚠ Skipping item '{item_name}': band not found")
            return
        
        # Prepare item payload
        item_payload = {
            'name': item_name,
            'type': item.get('type', 'MANUAL'),
            'start': item['start'],
            'duration': item.get('duration', 0),
            'tags': item.get('tags', []),
            'groupId': new_band_id
        }
        
        # Include optional fields if present
        if 'status' in item:
            item_payload['status'] = item['status']
        if 'activityDefinition' in item:
            item_payload['activityDefinition'] = item['activityDefinition']
        
        try:
            r = requests.post(f"{self.api_base}/items", json=item_payload)
            r.raise_for_status()
            print(f"    Added item: {item_name} (type: {item_payload['type']})")
        except requests.exceptions.HTTPError as e:
            print(f"    ✗ Error adding item '{item_name}': {e.response.text if hasattr(e, 'response') else e}")
    
    def list_views(self):
        """List all current timeline views"""
        views_data = self.get_all_views()
        views = views_data.get('views', [])
        
        # Get all bands and items
        bands_data = self.get_all_bands()
        all_bands = bands_data.get('bands', [])
        items_data = self.get_all_items()
        all_items = items_data.get('items', [])
        
        if not views and not all_bands and not all_items:
            print("No timeline views, bands, or items found")
            return
        
        if views:
            print(f"\nTimeline Views ({len(views)}):")
            print("=" * 80)
            for view in views:
                print(f"\n📋 {view['name']} (ID: {view['id']})")
        
        if all_bands:
            print(f"\nTimeline Bands ({len(all_bands)}):")
            print("=" * 80)
            
            for band in all_bands:
                band_id = band['id']
                band_items = [item for item in all_items if item.get('groupId') == band_id]
                
                print(f"\n  • {band['name']} ({band['type']}) - {len(band_items)} item(s)")
                print(f"    ID: {band_id}")
                if band.get('description'):
                    print(f"    Description: {band['description']}")
                
                if band['type'] == 'PARAMETER_PLOT':
                    params = [v for k, v in band.get('properties', {}).items() 
                             if k.endswith('_parameter')]
                    if params:
                        print(f"    Parameters: {', '.join(params)}")
                
                # Show first few items
                for item in band_items[:3]:
                    print(f"      - {item.get('name', 'Unnamed')} ({item.get('type', 'MANUAL')})")
                if len(band_items) > 3:
                    print(f"      ... and {len(band_items) - 3} more")
        
        # Show items without bands (orphaned)
        orphaned = [item for item in all_items if not item.get('groupId')]
        if orphaned:
            print(f"\n⚠ Orphaned Items (no band): {len(orphaned)}")
            for item in orphaned[:5]:
                print(f"  - {item.get('name', 'Unnamed')}")
    
    def export_to_directory(self, directory):
        """Export timeline to separate JSON files in a directory"""
        views_data = self.get_all_views()
        views = views_data.get('views', [])
        
        # Get all bands and items
        bands_data = self.get_all_bands()
        all_bands = bands_data.get('bands', [])
        items_data = self.get_all_items()
        all_items = items_data.get('items', [])
        
        if not views and not all_bands and not all_items:
            print("No timeline views, bands, or items found")
            return
        
        # Create directory if it doesn't exist
        Path(directory).mkdir(parents=True, exist_ok=True)
        
        # Export complete timeline as single file
        complete_file = os.path.join(directory, "complete_timeline.json")
        complete_data = {
            'views': views,
            'bands': all_bands,
            'items': all_items
        }
        with open(complete_file, 'w') as f:
            json.dump(complete_data, f, indent=2)
        print(f"✓ Exported complete timeline to {complete_file}")
        
        # Also export each band separately for easier viewing
        for band in all_bands:
            band_id = band['id']
            safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' 
                               for c in band['name'])
            filename = os.path.join(directory, f"band_{safe_name}.json")
            
            # Include items for this band
            band_items = [item for item in all_items if item.get('groupId') == band_id]
            
            export_data = {
                'band': band,
                'items': band_items
            }
            
            with open(filename, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            print(f"✓ Exported band '{band['name']}' ({len(band_items)} items) to {filename}")
        
        print(f"\n✓ Exported {len(views)} view(s), {len(all_bands)} band(s), and {len(all_items)} item(s) to {directory}/")
    
    def import_from_directory(self, directory):
        """Import timeline from JSON files in a directory"""
        # Look for complete timeline file first
        complete_file = os.path.join(directory, "complete_timeline.json")
        
        if os.path.exists(complete_file):
            print(f"Loading complete timeline from {complete_file}")
            self.load_from_file(complete_file)
            return
        
        # Otherwise try to load individual files
        json_files = list(Path(directory).glob('*.json'))
        
        if not json_files:
            print(f"No JSON files found in {directory}")
            return
        
        print(f"Importing {len(json_files)} file(s) from {directory}/...")
        
        band_id_map = {}
        
        for filepath in json_files:
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                
                # Support different formats
                if 'band' in data:
                    # Single band file
                    band = data['band']
                    items = data.get('items', [])
                    old_band_id = band.get('id')
                    new_band_id = self._restore_band_standalone(band)
                    if old_band_id and new_band_id:
                        band_id_map[old_band_id] = new_band_id
                    for item in items:
                        self._restore_item(item, band_id_map)
                elif 'views' in data:
                    # Complete timeline file
                    self.load_from_file(str(filepath))
                    
            except Exception as e:
                print(f"  ✗ Error importing {filepath.name}: {e}")
        
        print(f"✓ Import complete")
    
    def delete_all_views(self):
        """Delete all timeline views (use with caution!)"""
        views_data = self.get_all_views()
        views = views_data.get('views', [])
        
        if not views:
            print("No views to delete")
            return
        
        print(f"⚠ Deleting {len(views)} view(s)...")
        
        for view in views:
            try:
                r = requests.delete(f"{self.api_base}/views/{view['id']}")
                r.raise_for_status()
                print(f"  ✓ Deleted: {view['name']}")
            except requests.exceptions.HTTPError as e:
                print(f"  ✗ Error deleting '{view['name']}': {e}")


def main():
    parser = argparse.ArgumentParser(
        description='YAMCS Timeline Manager - Save and load timeline views',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list                        # List all current views
  %(prog)s save backup.json            # Save all views to file
  %(prog)s load backup.json            # Load views from file
  %(prog)s export                      # Export to timelines/ (default)
  %(prog)s export my_timelines/        # Export to custom directory
  %(prog)s import                      # Import from timelines/ (default)
  %(prog)s delete-all --confirm        # Delete all views (caution!)
        """
    )
    
    parser.add_argument('command', 
                       choices=['list', 'save', 'load', 'export', 'import', 'delete-all'],
                       help='Command to execute')
    parser.add_argument('path', nargs='?',
                       help='File or directory path (required for save/load, defaults to timelines/ for export/import)')
    parser.add_argument('--instance', default='shire',
                       help='YAMCS instance name (default: shire)')
    parser.add_argument('--url', default='http://localhost:8090',
                       help='YAMCS base URL (default: http://localhost:8090)')
    parser.add_argument('--confirm', action='store_true',
                       help='Confirm destructive operations')
    
    args = parser.parse_args()
    
    # Set default paths for export/import if not provided
    if args.command in ['export', 'import'] and not args.path:
        args.path = 'timelines/'
    
    # Validate path argument for save/load (required)
    if args.command in ['save', 'load'] and not args.path:
        parser.error(f"'{args.command}' command requires a path argument")
    
    manager = YAMCSTimelineManager(instance=args.instance, base_url=args.url)
    
    try:
        if args.command == 'list':
            manager.list_views()
        
        elif args.command == 'save':
            manager.save_to_file(args.path)
        
        elif args.command == 'load':
            manager.load_from_file(args.path)
        
        elif args.command == 'export':
            manager.export_to_directory(args.path)
        
        elif args.command == 'import':
            manager.import_from_directory(args.path)
        
        elif args.command == 'delete-all':
            if not args.confirm:
                print("⚠ This will delete ALL timeline views!")
                print("Add --confirm flag to proceed")
                sys.exit(1)
            manager.delete_all_views()
    
    except requests.exceptions.ConnectionError:
        print(f"✗ Error: Cannot connect to YAMCS at {args.url}")
        print(f"  Make sure YAMCS is running and accessible")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
