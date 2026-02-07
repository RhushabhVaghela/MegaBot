import { useState } from 'react';
import type { SearchResult } from '../types/index.ts';

interface MemoryPanelProps {
  categories: string[];
  searchResults: SearchResult[];
  onSearch: (query: string) => void;
}

export function MemoryPanel({ categories, searchResults, onSearch }: MemoryPanelProps) {
  const [searchQuery, setSearchQuery] = useState('');

  const handleSearch = () => {
    onSearch(searchQuery.trim() || 'all');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8" role="region" aria-label="Memory Hub">
      <h2 className="text-2xl font-bold mb-6 tracking-tight">Hierarchical Memory</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Categories Card */}
        <div className="bg-[#1e2330] p-6 rounded-sm border border-gray-800">
          <h3 className="text-sm font-semibold mb-4 flex items-center gap-2 uppercase tracking-wider text-gray-400">
            <span aria-hidden="true">📂</span> Categories
          </h3>
          {categories.length === 0 ? (
            <p className="text-sm text-gray-600">No categories yet.</p>
          ) : (
            <ul className="space-y-2 text-sm text-gray-400" aria-label="Memory categories">
              {categories.map((cat, idx) => (
                <li
                  key={idx}
                  className="py-1 px-2 rounded-sm hover:bg-gray-800 transition-colors cursor-default"
                >
                  {cat}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Results Card */}
        <div className="bg-[#1e2330] p-6 rounded-sm border border-gray-800 md:col-span-1 lg:col-span-2">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
              Recent Memory Items
            </h3>
          </div>

          <div className="flex gap-2 mb-4">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search memory..."
              className="flex-1 bg-[#0f1117] border border-gray-700 rounded-sm px-3 py-1.5 text-sm text-gray-200
                         placeholder:text-gray-600 focus:outline-none focus:border-teal-600 transition-colors"
              aria-label="Search memory"
            />
            <button
              onClick={handleSearch}
              className="text-xs bg-gray-800 hover:bg-gray-700 px-3 py-1.5 rounded-sm text-gray-400
                         transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-500"
              aria-label="Search memory items"
            >
              Search
            </button>
            <button
              onClick={() => onSearch('all')}
              className="text-xs bg-gray-800 hover:bg-gray-700 px-3 py-1.5 rounded-sm text-gray-400
                         transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-500"
              aria-label="Refresh memory items"
            >
              Refresh
            </button>
          </div>

          <div className="space-y-3">
            {searchResults.length === 0 ? (
              <p className="text-gray-600 text-sm py-8 text-center">
                No recent items. Click Refresh to load.
              </p>
            ) : (
              searchResults.map((item, idx) => (
                <div
                  key={idx}
                  className="p-3 bg-[#0f1117] rounded-sm border border-gray-700/60 text-sm text-gray-300 leading-relaxed"
                >
                  {item.content}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
